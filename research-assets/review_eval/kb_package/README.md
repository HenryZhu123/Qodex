# 408 教材知识库（SQLite 版）

面向考研 408 审校 Agent 的本地教材知识库。纯 SQLite，无外部服务、无网络依赖、无 API Key。
解开压缩包即可用。

**版本**：`2026.11`
**构建日期**：2026-11-09
**规模**：5 个分块索引、2,698 个 chunk、约 206 万字符

---

## 一、包里有什么

```
qodex-kb-sqlite-2026.11/
├── README.md                    本文件
├── MANIFEST.json                文件清单、sha256、条数（可用于校验完整性）
├── registry.sqlite              去重注册表（可选，见 §5）
└── books/
    ├── data_structure/
    │   └── kb.sqlite            严蔚敏《数据结构（C 语言版）》第 2 版，411 块
    ├── computer_organization/
    │   └── kb.sqlite            谭志虎《计算机组成原理》，625 块
    ├── operating_system/
    │   └── kb.sqlite            汤小丹《计算机操作系统（慕课版）》，601 块
    └── computer_network/
        ├── kb.sqlite            Kurose《计算机网络：自顶向下方法》第 7 版，875 块
        ├── kb_8th.sqlite        同书第 8 版，186 块（只含第 7 版没有的段落）
        └── relations.json       两版之间的对应关系（25 个冲突组、507 条等价别名）
```

`kb_8th.sqlite` 是**增量索引**：两版完全相同或仅 OCR 差异的段落不再重复收录，只保留第 8 版独有的内容。
跨版本检索时两个索引一起查（见 §4）。

---

## 二、表结构

每个 `kb.sqlite` 内部结构一致。

### documents（书籍元数据）

| 字段 | 含义 |
| --- | --- |
| `doc_id` | 书的内容哈希，作为主键 |
| `title` / `source_path` | 书名与原始 PDF 路径 |
| `parse_method` | 解析方式（`mineru` / `pymupdf`） |
| `char_count` / `unit_count` | 总字符数、总页数 |
| `metadata_json` | 其他元数据 |

### chunks（正文切片，核心表）

| 字段 | 含义 |
| --- | --- |
| `chunk_id` | 形如 `2367b64d37e4dadb:00651`，即 `doc_id:序号` |
| `content` | 教材原文（模型最终读到的内容） |
| `heading_path` | 章节路径，如 `第7章 > 7.3 无线局域网 > 7.3.3 IEEE 802.11 帧` |
| `page_start` / `page_end` | 页码（见 §6 限制） |
| `char_count` / `chunk_type` | 字符数、切片类型 |
| `content_hash` | 内容 sha256，用于去重 |
| `metadata_json` | 来源文件、标题、语言 |

### chunks_fts（全文检索虚表）

| 字段 | 含义 |
| --- | --- |
| `content_tokens` | **jieba 分词后的空格串**，FTS5 实际索引的就是这一列 |
| `chunk_id` | 对应 `chunks.chunk_id` |

检索用 `chunks_fts MATCH ?`，排序用 `bm25(chunks_fts)`（**值越小越相关**）。

---

## 三、最小可用示例（Python）

```python
import re
import sqlite3

import jieba

DB = "books/computer_network/kb.sqlite"


def build_match(query: str) -> str:
    """必须和建索引时用同样的分词，否则 0 命中。"""
    tokens = [t.strip() for t in jieba.cut(query) if len(t.strip()) >= 2]
    tokens += re.findall(r"[A-Za-z][A-Za-z0-9+#\-]{1,}", query)
    seen, uniq = set(), []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            uniq.append(token)
    return " OR ".join(f'"{t}"' for t in uniq[:16])


conn = sqlite3.connect(DB)
rows = conn.execute(
    """
    SELECT c.chunk_id, c.heading_path, c.page_start, c.content,
           bm25(chunks_fts) AS score
    FROM chunks_fts f
    JOIN chunks c ON c.chunk_id = f.chunk_id
    WHERE chunks_fts MATCH ?
    ORDER BY score ASC
    LIMIT 3
    """,
    (build_match("TCP 拥塞窗口 ssthresh"),),
).fetchall()

for chunk_id, heading, page, text, score in rows:
    print(f"{score:7.2f}  p{page}  {heading}")
    print(f"    {text[:120]}\n")
```

预期第一条落在第 3 章 TCP 拥塞控制一节，页码 196 附近。

---

## 四、四个学科一起查时的注意事项

**不要**把所有库塞进一次 MATCH。不同书的 BM25 分数分布不同，混排会互相干扰：
实测把四库合并排序，recall@2 从 86.3% 掉到 77.5%（正确的块被别科的长段落挤掉）。

正确做法：先按考点判定学科，只查对应那本；判不出来时再依次查四本，各自保留名次再比较。
实测数据见仓库 `research-assets/review_eval/retrieval_eval/`。

---

## 五、registry.sqlite（可选）

整库范围的去重注册表，用于**以后加新书时**判断是否重复：

| 表 | 内容 |
| --- | --- |
| `documents` | 已入库的 4 本书（哈希、标题、版次、作者指纹） |
| `chunk_registry` | 2,508 条 chunk 指纹 |

只做检索的话不需要它，可以删掉。

---

## 六、已知限制

1. **第 8 版页码是分卷精度**。该版是扫描件，经 MinerU 分 26 卷解析，页码只能定位到卷，不是真实页。其余四本来自文本层 PDF，页码准确。
2. **第 8 版有 OCR 噪声**。扫描件识别会偶发错字（如"地址 l"应为"地址 1"）。引用以第 7 版为准，第 8 版只用于查新增内容。
3. **没有向量检索**。全部是 BM25 稀疏检索，同义改写、跨表述查询召不回来。要加稠密检索需自行生成 embedding。
4. **未分词查询必然 0 命中**。`chunks_fts` 索引的是 jieba 分词结果，直接搜 `突发传输` 匹配不到，必须先切成 `突发 传输`。
5. **覆盖有缺口**。实测 80 条真实查询 recall@2 = 86.3%；漏的 11 条里 6 条是教材确实没写（如 B 树定义在严蔚敏书中极简、Kurose 不讲以太网 64 字节最小帧长）。

---

## 七、使用范围

教材正文来源于正式出版教材，**仅供组内研究与开发使用**，不要公开分发、不要上传到公开仓库或公开镜像。

---

## 八、校验

```bash
# 与 MANIFEST.json 中的 sha256 对比
sha256sum books/*/kb.sqlite books/computer_network/kb_8th.sqlite

# chunk 总数应为 2698
sqlite3 books/*/kb.sqlite 'select count(*) from chunks'
```
