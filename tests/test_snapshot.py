from decimal import Decimal
import copy
import json
import unittest
from pathlib import Path

from warehouse.build import order_snapshot
from warehouse.controls import inspect
from warehouse.facts import order_facts, receipt_facts, shipment_facts
from warehouse.ingest import ingest
from warehouse.queries import line_quantities
from warehouse.storage import open_store
import tempfile


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.connection = open_store(self.root / 'store.duckdb')
        self.sample = json.loads(Path('samples/delivery.json').read_text())

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def load(self, payload):
        return ingest(self.connection, payload)

    def package(self, pack_id='p', sku='book', pieces_per_box='10'):
        return {'pack_id':pack_id,'sku':sku,'pieces_per_box':pieces_per_box}

    def order(self, line_id='l', quantity='3', unit='box', pack_id='p', sku='book',
              amount='99'):
        return {'line_id':line_id,'sku':sku,'pack_id':pack_id,'quantity':quantity,
                'unit':unit,'amount':amount,'promised_at':'2026-01-10T00:00:00Z'}

    def shipment(self, shipment_id='s', line_id='l', at='2026-01-02T00:00:00Z',
                 quantity='10', unit='piece'):
        return {'shipment_id':shipment_id,'line_id':line_id,'occurred_at':at,
                'quantity':quantity,'unit':unit}

    def receipt(self, receipt_id='r', shipment_id='s', at='2026-01-03T00:00:00Z',
                quantity='10', unit='piece'):
        return {'receipt_id':receipt_id,'shipment_id':shipment_id,'occurred_at':at,
                'quantity':quantity,'unit':unit}

    def cancel(self, cancel_id='c', line_id='l', at='2026-01-01T00:00:00Z',
               quantity='1', unit='box', phase='unshipped'):
        return {'cancel_id':cancel_id,'line_id':line_id,'occurred_at':at,
                'quantity':quantity,'unit':unit,'phase':phase}

    def ret(self, return_id='t', shipment_id='s', at='2026-01-04T00:00:00Z',
            quantity='1', unit='piece', phase='requested'):
        return {'return_id':return_id,'shipment_id':shipment_id,'occurred_at':at,
                'quantity':quantity,'unit':unit,'phase':phase}

    def batch(self, name='b', **tables):
        return {'batch_id':name,'tables':tables}

    def line(self, line_id='l'):
        return next(row for row in order_snapshot(self.connection)['lines']
                    if row['line_id'] == line_id)

    def test_sample_accumulates_all_quantities(self):
        self.load(self.sample)
        line = self.line('l1')
        self.assertEqual(line['ordered_pieces'], Decimal(24))
        self.assertEqual(line['committed_pieces'], Decimal(12))
        self.assertEqual(line['shipped_pieces'], Decimal(12))
        self.assertEqual(line['received_pieces'], Decimal(7))
        self.assertEqual(line['unfulfilled_pieces'], Decimal(0))
        self.assertEqual(line['return_pending_pieces'], Decimal(3))
        self.assertEqual(line['returned_pieces'], Decimal(2))
        self.assertEqual(line['net_received_pieces'], Decimal(5))
        self.assertEqual(line['first_shipped_at'],'2026-11-09T12:00:00+00:00')
        self.assertEqual(line['all_shipped_at'],'2026-11-09T12:00:00+00:00')
        self.assertIsNone(line['all_received_at'])
        self.assertFalse(line['received_complete'])

    def test_split_shipments_do_not_duplicate_order_value(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='2',amount='100')],
                                       'shipments':[self.shipment('s1',quantity='10'),
                                                    self.shipment('s2',quantity='10')]}))
        snapshot = order_snapshot(self.connection)
        line = snapshot['lines'][0]
        self.assertEqual(len(snapshot['lines']),1)
        self.assertEqual(line['amount'],Decimal(100))
        self.assertEqual(line['shipped_pieces'],Decimal(20))
        self.assertEqual(line['unfulfilled_pieces'],Decimal(0))
        self.assertEqual({entry['goal_id'] for entry in snapshot['details']
                          if entry['goal_kind']=='shipment'}, {'s1','s2'})

    def test_split_receipts_cannot_exceed_shipment(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'shipments':[self.shipment(quantity='10')],
                                       'receipts_business':[self.receipt('r1',quantity='7'),
                                                            self.receipt('r2',quantity='7')]}))
        snapshot = order_snapshot(self.connection)
        self.assertEqual(snapshot['lines'][0]['received_pieces'],Decimal(10))
        self.assertEqual(snapshot['discrepancies'][0]['reason'],'签收超过对应发运数量')
        self.assertEqual(snapshot['discrepancies'][0]['applied_pieces'],Decimal(3))

    def test_packaging_uses_order_version_not_latest(self):
        self.load(self.batch('base',**{'packaging':[self.package('old','book','12'),
                                                    self.package('new','book','6')],
                                       'order_lines':[self.order(pack_id='old',quantity='1',
                                                                 unit='box')],
                                       'shipments':[self.shipment(quantity='1',unit='box')]}))
        line = self.line()
        self.assertEqual(line['ordered_pieces'],Decimal(12))
        self.assertEqual(line['shipped_pieces'],Decimal(12))

    def test_mixed_units_across_shipments(self):
        self.load(self.batch('base',**{'packaging':[self.package('p','book','12')],
                                       'order_lines':[self.order(quantity='2',unit='box')],
                                       'shipments':[self.shipment('s1',quantity='1',unit='box'),
                                                    self.shipment('s2',quantity='5',unit='piece')],
                                       'receipts_business':[self.receipt('r1','s1',quantity='4'),
                                                            self.receipt('r2','s2',quantity='5')]}))
        line = self.line()
        self.assertEqual(line['shipped_pieces'],Decimal(17))
        self.assertEqual(line['received_pieces'],Decimal(9))
        self.assertEqual(line['unfulfilled_pieces'],Decimal(7))

    def test_unshipped_cancel_reduces_commitment(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='3')],
                                       'shipments':[self.shipment(quantity='20')],
                                       'receipts_business':[self.receipt(quantity='20')],
                                       'cancellations':[self.cancel(quantity='1')]}))
        line = self.line()
        self.assertEqual(line['committed_pieces'],Decimal(20))
        self.assertEqual(line['unfulfilled_pieces'],Decimal(0))
        self.assertEqual(line['net_received_pieces'],Decimal(20))
        self.assertTrue(line['received_complete'])

    def test_after_dispatch_cancel_does_not_undo_shipment(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='3')],
                                       'shipments':[self.shipment(quantity='30')],
                                       'cancellations':[self.cancel(quantity='2',
                                           phase='requested_after_dispatch')]}))
        line = self.line()
        self.assertEqual(line['shipped_pieces'],Decimal(30))
        self.assertEqual(line['committed_pieces'],Decimal(30))
        self.assertEqual(line['after_dispatch_cancel_pieces'],Decimal(20))
        self.assertEqual(line['first_shipped_at'],'2026-01-02T00:00:00+00:00')
        self.assertEqual(line['all_shipped_at'],'2026-01-02T00:00:00+00:00')

    def test_return_request_is_not_a_warehouse_return(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'shipments':[self.shipment(quantity='10')],
                                       'receipts_business':[self.receipt(quantity='10')],
                                       'returns':[self.ret(quantity='4',phase='requested')]}))
        line = self.line()
        self.assertEqual(line['return_pending_pieces'],Decimal(4))
        self.assertEqual(line['returned_pieces'],Decimal(0))
        self.assertEqual(line['net_received_pieces'],Decimal(10))
        self.assertTrue(line['received_complete'])

    def test_received_return_moves_pending_to_returned(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'shipments':[self.shipment(quantity='10')],
                                       'receipts_business':[self.receipt(quantity='10')],
                                       'returns':[self.ret('t1',quantity='4',phase='requested'),
                                                  self.ret('t2',quantity='4',phase='received')]}))
        line = self.line()
        self.assertEqual(line['return_pending_pieces'],Decimal(4))
        self.assertEqual(line['returned_pieces'],Decimal(4))
        self.assertEqual(line['net_received_pieces'],Decimal(6))

    def test_completion_is_kept_after_later_return(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'shipments':[self.shipment(quantity='10')],
                                       'receipts_business':[self.receipt(quantity='10')]}))
        self.assertTrue(self.line()['received_complete'])
        self.assertEqual(self.line()['all_received_at'],'2026-01-03T00:00:00+00:00')
        self.load(self.batch('later',**{'returns':[self.ret(quantity='4',phase='received')]}))
        line = self.line()
        self.assertFalse(line['received_complete'])
        self.assertEqual(line['all_received_at'],'2026-01-03T00:00:00+00:00')

    def test_late_cancel_after_completion_does_not_erase_milestone(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'shipments':[self.shipment(quantity='10')],
                                       'receipts_business':[self.receipt(quantity='10')]}))
        self.load(self.batch('later',**{'cancellations':[self.cancel(
            quantity='1',at='2026-01-09T00:00:00Z')]}))
        line = self.line()
        self.assertFalse(line['received_complete'])
        self.assertEqual(line['all_received_at'],'2026-01-03T00:00:00+00:00')

    def test_milestone_two_trucks(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='3')],
                                       'shipments':[self.shipment('s1',quantity='10'),
                                                    self.shipment('s2',quantity='10',
                                                                  at='2026-01-05T00:00:00Z')],
                                       'receipts_business':[
                                           self.receipt('r1','s1',quantity='10')]}))
        line = self.line()
        self.assertIsNone(line['all_shipped_at'])
        self.load(self.batch('more',**{'shipments':[self.shipment('s3',quantity='10',
                                                                  at='2026-01-07T00:00:00Z')]}))
        line = self.line()
        self.assertEqual(line['all_shipped_at'],'2026-01-07T00:00:00+00:00')
        self.assertIsNone(line['all_received_at'])
        self.load(self.batch('last',**{'receipts_business':[
            self.receipt('r2','s2',quantity='10',at='2026-01-06T00:00:00Z'),
            self.receipt('r3','s3',quantity='10',at='2026-01-08T00:00:00Z')]}))
        line = self.line()
        self.assertEqual(line['all_received_at'],'2026-01-08T00:00:00+00:00')

    def test_receipt_before_its_shipment_is_blocked(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'shipments':[self.shipment(at='2026-01-05T00:00:00Z')],
                                       'receipts_business':[self.receipt(at='2026-01-02T00:00:00Z')]}))
        snapshot = order_snapshot(self.connection)
        line = snapshot['lines'][0]
        self.assertTrue(line['blocked'])
        self.assertIsNone(line['all_received_at'])
        self.assertIsNone(line['received_complete'])
        self.assertEqual(snapshot['issues'][0]['reason'],'签收早于对应发运')
        self.assertEqual(line['received_pieces'],Decimal(0))

    def test_missing_references_are_reported_not_negative(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'shipments':[self.shipment(quantity='10')],
                                       'receipts_business':[self.receipt('r1','ghost')],
                                       'returns':[self.ret('t1','ghost')],
                                       'cancellations':[self.cancel('c1',line_id='ghost')]}))
        snapshot = order_snapshot(self.connection)
        reasons = {issue['id']:issue['reason'] for issue in snapshot['issues']}
        self.assertEqual(reasons['r1'],'尚无对应发运')
        self.assertEqual(reasons['t1'],'发运引用未知')
        self.assertEqual(reasons['c1'],'订单行引用未知')
        self.assertEqual(snapshot['lines'][0]['received_pieces'],Decimal(0))
        self.assertGreaterEqual(snapshot['lines'][0]['unfulfilled_pieces'],Decimal(0))

    def test_excess_return_is_capped_and_reported(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'shipments':[self.shipment(quantity='10')],
                                       'returns':[self.ret('t1',quantity='4',phase='received'),
                                                  self.ret('t2',quantity='9',phase='received')]}))
        snapshot = order_snapshot(self.connection)
        line = snapshot['lines'][0]
        self.assertEqual(line['returned_pieces'],Decimal(10))
        self.assertEqual(snapshot['discrepancies'][0]['reason'],'退货数量超过相应发运数量')

    def test_cancel_beyond_order_is_capped(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'cancellations':[self.cancel(quantity='3')]}))
        snapshot = order_snapshot(self.connection)
        line = snapshot['lines'][0]
        self.assertEqual(line['committed_pieces'],Decimal(0))
        self.assertEqual(line['unfulfilled_pieces'],Decimal(0))
        self.assertEqual(snapshot['discrepancies'][0]['reason'],'取消数量超过应履约数量')

    def test_details_explain_each_quantity(self):
        self.load(self.sample)
        detail = line_quantities(self.connection,'l1')
        self.assertEqual(detail['line']['ordered_pieces'],Decimal(24))
        events = {entry['event']:entry for entry in detail['details']}
        self.assertEqual(events['shipment']['event_id'],'s1')
        self.assertEqual(events['receipt']['applied_pieces'],Decimal(7))
        self.assertEqual(events['cancel_unshipped']['applied_pieces'],Decimal(12))
        self.assertIsNone(line_quantities(self.connection,'missing'))

    def test_independent_queries_are_unchanged(self):
        self.load(self.sample)
        self.assertEqual(order_facts(self.connection)[0]['ordered_pieces'],24)
        self.assertEqual(shipment_facts(self.connection)[0]['pieces'],12)
        self.assertEqual(receipt_facts(self.connection)[0]['pieces'],7)
        self.assertEqual(receipt_facts(self.connection)[0]['issue'],None)

    def test_arrival_order_does_not_change_result(self):
        tables = {'packaging':[self.package()],
                  'order_lines':[self.order(quantity='2')],
                  'shipments':[self.shipment('s1',quantity='10'),
                               self.shipment('s2',at='2026-01-05T00:00:00Z',quantity='10')],
                  'receipts_business':[self.receipt('r1','s1',quantity='10'),
                                       self.receipt('r2','s2',at='2026-01-06T00:00:00Z',
                                                    quantity='10')],
                  'returns':[self.ret('t1','s1',quantity='2',phase='received')],
                  'cancellations':[self.cancel(quantity='1',at='2026-01-07T00:00:00Z')]}
        first = copy.deepcopy(tables)
        self.load(self.batch('one',**first))
        expected = line_quantities(self.connection,'l')
        for name in reversed(list(tables)):
            self.load({'batch_id':'part-'+name,'tables':{name:copy.deepcopy(tables[name])}})
        self.assertEqual(line_quantities(self.connection,'l')['line'],expected['line'])
        self.assertEqual(len(line_quantities(self.connection,'l')['details']),
                         len(expected['details']))

    def test_controls_record_blocking_reasons(self):
        self.load(self.batch('base',**{'packaging':[self.package()],
                                       'order_lines':[self.order(quantity='1')],
                                       'shipments':[self.shipment(quantity='20')]}))
        issues = inspect(self.connection)
        self.assertEqual(issues[0]['reason'],'累计发运超过订单数量')
        stored = self.connection.execute(
            'SELECT entity_kind,entity_id,reason FROM dispatch_issues ORDER BY entity_id').fetchall()
        self.assertEqual(stored,[('order','l','累计发运超过订单数量')])


if __name__ == '__main__':
    unittest.main()
