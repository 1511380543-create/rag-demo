-- RAG 项目 MySQL 初始化脚本
-- 用途：存储文档 chunks 与 metadata
-- 兼容：MySQL 8.0+

CREATE DATABASE IF NOT EXISTS `rag_demo`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE `rag_demo`;

-- 抽取文档表：存储 PDF 抽取后的 blocks 与 full_text
CREATE TABLE IF NOT EXISTS `rag_documents` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `doc_id` VARCHAR(128) NOT NULL COMMENT '业务文档ID',
  `file_path` VARCHAR(512) NOT NULL COMMENT '抽取时的本地PDF路径',
  `extract_version` VARCHAR(64) NOT NULL COMMENT '抽取器版本',
  `page_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '有效页数',
  `char_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'full_text字符数',
  `full_text` LONGTEXT NOT NULL COMMENT '供切块层读取的全文',
  `blocks` JSON NOT NULL COMMENT '有序块数组(title/paragraph/list_item/table)',
  `extract_report` JSON NULL COMMENT '抽取统计报告',
  `metadata` JSON NULL COMMENT '文档级元数据',
  `content_hash` CHAR(64) NOT NULL COMMENT 'full_text内容哈希',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_doc_id` (`doc_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG抽取文档表';

-- 分片表：仅存储每个文档切分后的chunk文本与元数据
CREATE TABLE IF NOT EXISTS `rag_chunks` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `doc_id` VARCHAR(128) NOT NULL COMMENT '业务文档ID',
  `chunk_index` INT UNSIGNED NOT NULL COMMENT '文档内chunk序号，从0开始',
  `chunk_text` LONGTEXT NOT NULL COMMENT 'chunk原文',
  `metadata` JSON NULL COMMENT 'chunk级元数据',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_doc_chunk_index` (`doc_id`, `chunk_index`),
  KEY `idx_doc_id` (`doc_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG分片表';

-- 查询监控日志表：记录每次查询的延迟、召回与分数指标
CREATE TABLE IF NOT EXISTS `rag_query_logs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `query_text` TEXT NOT NULL COMMENT '查询文本',
  `top_k` INT UNSIGNED NOT NULL COMMENT '本次查询top_k',
  `filters_applied` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '是否启用元数据过滤:0否1是',
  `embed_ms` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '向量化耗时(毫秒)',
  `retrieve_ms` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '检索耗时(毫秒)',
  `total_ms` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '总耗时(毫秒)',
  `retrieved_before_filter` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '过滤前召回数',
  `retrieved_after_filter` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '过滤后召回数',
  `is_empty_recall` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '是否空召回:0否1是',
  `top_score` DOUBLE NULL COMMENT '最高分,仅记录不参与过滤',
  `min_score_value` DOUBLE NULL COMMENT '最低分,仅记录不参与过滤',
  `avg_score` DOUBLE NULL COMMENT '平均分,仅记录不参与过滤',
  `error_code` VARCHAR(64) NULL COMMENT '失败错误码,成功为空',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG查询监控日志表';

-- 评测集表：维护检索质量评测的黄金样本
CREATE TABLE IF NOT EXISTS `rag_eval_dataset` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `case_id` VARCHAR(128) NOT NULL COMMENT '评测用例业务ID',
  `query_text` TEXT NOT NULL COMMENT '评测查询文本',
  `relevant_chunk_ids` JSON NULL COMMENT 'chunk级标注',
  `expected_keywords` JSON NULL COMMENT '关键词命中标注',
  `evidence_keys` JSON NULL COMMENT '稳定证据键(doc_id/anchor_text/content_hash)',
  `keyword_match_mode` VARCHAR(8) NOT NULL DEFAULT 'any' COMMENT '关键词匹配模式:any任一/all全部',
  `top_k` INT UNSIGNED NULL COMMENT '样本级top_k',
  `enabled` TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '是否参与评测:0否1是',
  `expect_hit` TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '期望命中:1正样本0负样本',
  `filters` JSON NULL COMMENT '样本级元数据过滤(与query.filters同语义)',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_case_id` (`case_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG评测集表';

-- 评测轮次汇总表：记录每次评测的整体指标
CREATE TABLE IF NOT EXISTS `rag_eval_runs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID,即run_id',
  `dataset_size` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '参与评测样本数',
  `top_k` INT UNSIGNED NOT NULL COMMENT '本轮实际检索窗口回显(请求级覆盖或样本众数)',
  `avg_hit` DOUBLE NOT NULL DEFAULT 0 COMMENT '平均命中率',
  `avg_recall` DOUBLE NOT NULL DEFAULT 0 COMMENT '平均召回率',
  `avg_mrr` DOUBLE NOT NULL DEFAULT 0 COMMENT '平均MRR',
  `avg_latency_ms` DOUBLE NOT NULL DEFAULT 0 COMMENT '平均检索延迟(毫秒)',
  `note` VARCHAR(255) NULL COMMENT '本轮备注',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG评测轮次汇总表';

-- 评测逐条明细表：记录每个样本在某轮评测中的指标
CREATE TABLE IF NOT EXISTS `rag_eval_run_items` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `run_id` BIGINT UNSIGNED NOT NULL COMMENT '关联rag_eval_runs.id',
  `case_id` VARCHAR(128) NOT NULL COMMENT '评测用例业务ID',
  `query_text` TEXT NOT NULL COMMENT '评测查询文本',
  `hit` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '是否命中:0否1是',
  `recall` DOUBLE NOT NULL DEFAULT 0 COMMENT '单条召回率',
  `mrr` DOUBLE NOT NULL DEFAULT 0 COMMENT '单条MRR',
  `latency_ms` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '单条检索耗时(毫秒)',
  `retrieved_chunk_ids` JSON NULL COMMENT '实际召回的chunk_id列表',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_run_id` (`run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG评测逐条明细表';

-- 切块冻结版元数据：必要时手动打一版（非 VIEW；第二轮落地，见 07 §3.2.2）
CREATE TABLE IF NOT EXISTS `rag_eval_chunk_freezes` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID,即freeze_id',
  `freeze_label` VARCHAR(128) NOT NULL COMMENT '冻结版可读标签',
  `note` VARCHAR(255) NULL COMMENT '打版原因',
  `pipeline_version` VARCHAR(64) NULL COMMENT '切块/pipeline版本备注',
  `doc_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '纳入文档数',
  `chunk_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '纳入chunk数',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '打版时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_freeze_label` (`freeze_label`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG评测切块冻结版元数据表';

-- 切块冻结明细：拷贝打版当时的 chunk 正文，供金标可复现对比
CREATE TABLE IF NOT EXISTS `rag_eval_chunk_snapshot_items` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `freeze_id` BIGINT UNSIGNED NOT NULL COMMENT '关联rag_eval_chunk_freezes.id',
  `doc_id` VARCHAR(128) NOT NULL COMMENT '文档业务ID',
  `chunk_index` INT UNSIGNED NOT NULL COMMENT '文档内chunk序号',
  `chunk_text` MEDIUMTEXT NOT NULL COMMENT '冻结时chunk正文',
  `content_hash` CHAR(64) NOT NULL COMMENT '正文SHA-256 hex',
  `source_chunk_id` BIGINT UNSIGNED NULL COMMENT '打版当时rag_chunks.id',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '写入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_freeze_doc_index` (`freeze_id`, `doc_id`, `chunk_index`),
  KEY `idx_freeze_id` (`freeze_id`),
  KEY `idx_content_hash` (`content_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG评测切块冻结明细表';
