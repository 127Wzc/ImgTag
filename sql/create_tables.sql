
-- 确保已启用 pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 如果 images 已存在，先备份或直接删表
DROP TABLE IF EXISTS public.images CASCADE;

CREATE TABLE public.images (
  id          SERIAL PRIMARY KEY,
  image_url   TEXT       NOT NULL,
  tags        TEXT[]     NOT NULL,         -- 离散标签
  description TEXT       NOT NULL,         -- 自然语言描述
  embedding   VECTOR(512)                  -- 描述+标签 拼接后编码
);

-- GIN 索引：tags 精确 / overlap / contains
CREATE INDEX idx_tags ON public.images
       USING gin (tags);

-- 向量索引：HNSW 余弦
CREATE INDEX idx_embed_hnsw ON public.images
       USING hnsw (embedding vector_cosine_ops);


-- 添加说明
COMMENT ON TABLE images IS '存储图像URL、标签、描述和向量表示';
COMMENT ON COLUMN images.image_url IS '图像URL地址';
COMMENT ON COLUMN images.tags IS '图像标签数组';
COMMENT ON COLUMN images.description IS '图像描述文本'; 
COMMENT ON COLUMN images.embedding IS '使用模型生成的768维向量';