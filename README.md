# 海外发行订单履约明细仓

这是用于本地数据接收、事实核对和列式交换的仓库服务。数据使用 DuckDB 持久化，导出为 Parquet；不需要远程数据库或运行期网络。示例数据仅为本地合成的业务记录。

## 现有业务

订单、发运和签收事实分别可查，件箱换算固定使用订单所引用的包装版本，不能使用商品最新包装。取消和退货保留独立记录及业务阶段；退货记录按发运引用，申请与实际回仓分别累计，当前没有订单累积快照。未能配对发运的签收保留缺口，不直接丢弃或记零。

`warehouse.build.order_snapshot` 在既有事实之上按订单行累积承诺、已发、已收、未履约、退货中、已退回和净签收数量，并给出首次发运、应履约数量全部发运、全部签收的里程碑。快照只读取事实表，不写回也不改变各表原来的取数方式；`warehouse.queries.line_quantities` 可从累积结果查回每一笔数量依据。拆分发运或拆分包裹只增加发运、签收明细，订单金额始终只取订单行；签收和退货按各自发运的件数封顶，超出部分单独列为差异，不会写成负数或塞入未履约。未发取消下调应履约数量，发出后的取消申请只记录不冲减已发；退货申请计为退货中，实际回仓才计为已退回。里程碑按单据自身发生时间计算，同一组合法单据按不同到达顺序补录结果一致；后续变化会更新“完成”判定，但不会抹去曾经达到过的里程碑时刻。

`controls.inspect` 保存超额发运、缺少原单签收、签收早于对应发运、引用不完整等阻塞原因及数量差异。异常检查保留来源引用，独立事实查询不以是否通过检查为条件丢失记录。

## 使用

运行时支持 Python 3.11.x，独立容器使用摘要固定的 Python 3.11 镜像。`requirements.txt` 精确锁定依赖版本，`requirements.lock` 保存相同版本的 Linux CPython 3.11 wheel 哈希，容器构建时校验哈希。推荐使用下列容器方式；镜像构建时准备依赖，之后运行不联网。镜像只包含本仓库应用及依赖，不启动额外服务。

```bash
docker build -t fulfillment-warehouse .
docker run --rm --network none fulfillment-warehouse
```

已经准备依赖的环境中也可以直接执行：

```bash
python -m unittest discover -s tests -v
python -m compileall -q warehouse tests
python -m warehouse.cli --database /tmp/fulfillment.duckdb load samples/delivery.json
python -m warehouse.cli --database /tmp/fulfillment.duckdb overview
python -m warehouse.cli --database /tmp/fulfillment.duckdb snapshot
python -m warehouse.cli --database /tmp/fulfillment.duckdb snapshot --line l1
python -m warehouse.cli --database /tmp/fulfillment.duckdb export /tmp/fulfillment-exports release1
```

上面的导出版本不可覆盖；再次核对应使用新的数据库路径和新的导出目录，或直接运行使用临时目录的测试。测试同时验证接收事务、业务主键冲突、批号重送、持久化及列式文件回读。完整测试和样本运行通常数秒结束，没有等待外部服务的步骤。

## 数据与接口

构建所需工具和传递依赖同样精确锁定，并包含在容器依赖中。执行 `python -m build --wheel --no-isolation` 可在不下载额外构建依赖的情况下生成 wheel；SQL 表定义随包分发。

接收包包含 `batch_id` 和 `tables`。合法字段由各表契约与领域校验共同约束；同批号同内容重送不重复写入，同业务键异内容拒绝整个接收事务。已有原始行和接收回执保留，业务值更正须采用领域中允许的独立记录，不能覆写原行。

`warehouse.storage.open_store` 打开仓库，`warehouse.ingest.ingest` 接收业务包，`warehouse.queries` 提供现有事实查询。`warehouse.export.export_tables` 固定一次读取视图并生成版本目录，`read_export` 校验成员文件摘要后读取。`samples/delivery.json` 展示各表的当前字段和合法数据。

领域校验、事实计算与查询分别存在于同一应用的不同职责中。SQL 定义保存当前存储契约；批号回执与原始行登记属于接收事务，不是业务汇总来源。文件导出只交换现有业务表，接收回执不会充当事实行。
