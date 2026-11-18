CREATE TABLE IF NOT EXISTS receipts(batch_id VARCHAR PRIMARY KEY, signature VARCHAR NOT NULL, inserted INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS source_rows(table_name VARCHAR, row_key VARCHAR, payload VARCHAR NOT NULL, batch_id VARCHAR NOT NULL, PRIMARY KEY(table_name,row_key));
        CREATE TABLE IF NOT EXISTS packaging(pack_id VARCHAR PRIMARY KEY, sku VARCHAR, pieces_per_box DECIMAL(18,4));
        CREATE TABLE IF NOT EXISTS order_lines(line_id VARCHAR PRIMARY KEY, sku VARCHAR, pack_id VARCHAR, quantity DECIMAL(18,4), unit VARCHAR, amount DECIMAL(18,4), promised_at VARCHAR);
        CREATE TABLE IF NOT EXISTS shipments(shipment_id VARCHAR PRIMARY KEY, line_id VARCHAR, occurred_at VARCHAR, quantity DECIMAL(18,4), unit VARCHAR);
        CREATE TABLE IF NOT EXISTS receipts_business(receipt_id VARCHAR PRIMARY KEY, shipment_id VARCHAR, occurred_at VARCHAR, quantity DECIMAL(18,4), unit VARCHAR);
        CREATE TABLE IF NOT EXISTS cancellations(cancel_id VARCHAR PRIMARY KEY, line_id VARCHAR, occurred_at VARCHAR, quantity DECIMAL(18,4), unit VARCHAR, phase VARCHAR);
        CREATE TABLE IF NOT EXISTS returns(return_id VARCHAR PRIMARY KEY, shipment_id VARCHAR, occurred_at VARCHAR, quantity DECIMAL(18,4), unit VARCHAR, phase VARCHAR);

CREATE TABLE IF NOT EXISTS dispatch_issues(issue_id VARCHAR PRIMARY KEY, entity_kind VARCHAR, entity_id VARCHAR, payload VARCHAR, reason VARCHAR);