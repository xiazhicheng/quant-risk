# 产业链数据目录

**结构**: `research/chain/{code}.yaml` — 每只股票一个 YAML 文件

## 命名规则

文件名 = 股票代码（无前导零），如 `02460.yaml` 对应华润饮料。

## YAML 文件格式

严格遵循 ai-berkshire `industry-research.md` SOP，包含 7 个区块：

| 区块 | 字段 | 必填 | 说明 |
|------|------|:----:|------|
| 基础信息 | `code`, `name`, `industry` | ✅ | 股票代码/名称/行业 |
| 投资逻辑链 | `logic_chain` | ✅ | 底层趋势 → 需求 → 瓶颈 |
| 产业链全景图 | `chain` | ✅ | 上下游节点 + 连接关系 |
| 卡脖子环节 | `bottleneck`, `vs_leader` | ✅ | 关键制约 + 竞品对标 |
| 生意特征 | `business_traits` | ❌ | 各段毛利率/壁垒（大师分析用） |
| 文明趋势 | `civilization` | ❌ | 10年趋势判断 |

## 生成流程（LLM 操作）

当新股票进入分析范围（如推荐 TOP10）但无产业链数据时：

1. 读取本 README 了解 YAML 格式
2. 按 ai-berkshire SOP 步骤生成 YAML 内容
3. 写入 `research/chain/{code}.yaml`
4. 渲染器 `chain_renderer.py` 自动从 YAML 生成 Mermaid

## 数据来源规范

- 产业链节点和关系：基于 LLM 行业研究 + web_search 验证
- 每个 YAML 文件生成时必须标注数据验证状态
- 数据过时 >6 个月需重新生成
