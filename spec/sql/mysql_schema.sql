-- RAG 项目 MySQL 初始化脚本
-- 用途：存储文档 chunks 与 metadata
-- 兼容：MySQL 8.0+

CREATE DATABASE IF NOT EXISTS `rag_demo`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE `rag_demo`;

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
