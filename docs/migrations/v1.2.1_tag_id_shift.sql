-- ================================================
-- ImgTag 标签 ID 迁移脚本 v1.0
-- 目的：将现有标签 ID 偏移 +1000，为系统标签预留 1-999
-- 执行前请备份数据库！
-- ================================================

BEGIN;

-- 1. 临时禁用 image_tags 外键约束
ALTER TABLE image_tags DROP CONSTRAINT IF EXISTS image_tags_tag_id_fkey;

-- 2. 偏移 tags 表 ID（偏移量 1000）
UPDATE tags SET id = id + 1000;

-- 3. 同步更新 image_tags 表中的 tag_id
UPDATE image_tags SET tag_id = tag_id + 1000;

-- 4. 更新 tags 表中的 parent_id（自引用外键）
UPDATE tags SET parent_id = parent_id + 1000 WHERE parent_id IS NOT NULL;

-- 5. 重建外键约束
ALTER TABLE image_tags 
ADD CONSTRAINT image_tags_tag_id_fkey 
FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE;

-- 6. 重置 tags 表序列（确保新 ID 从 max+1 开始）
SELECT setval('tags_id_seq', (SELECT COALESCE(MAX(id), 1000) FROM tags));

-- 7. 更新现有标签的 level 为 2（普通标签）
UPDATE tags SET level = 2 WHERE level = 1;

-- 8. 插入系统分辨率标签 (level=1, id=100-105)
INSERT INTO tags (id, name, level, source, description, sort_order) VALUES
    (100, '8K', 1, 'system', '超高清 8K 分辨率 (≥7680px)', 100),
    (101, '4K', 1, 'system', '超高清 4K 分辨率 (≥3840px)', 101),
    (102, '2K', 1, 'system', '高清 2K 分辨率 (≥2560px)', 102),
    (103, '1080p', 1, 'system', '全高清 1080p (≥1920px)', 103),
    (104, '720p', 1, 'system', '高清 720p (≥1280px)', 104),
    (105, 'SD', 1, 'system', '标清 (<1280px)', 105)
ON CONFLICT (name) DO UPDATE SET 
    id = EXCLUDED.id,
    level = EXCLUDED.level, 
    source = EXCLUDED.source,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order;

-- 9. 插入默认主分类 (level=0, id=1-9)
INSERT INTO tags (id, name, level, source, description, sort_order) VALUES
    (1, '风景', 0, 'system', '自然风光、城市景观', 1),
    (2, '人像', 0, 'system', '真人照片、人物特写', 2),
    (3, '动漫', 0, 'system', '动画、漫画、二次元', 3),
    (4, '表情包', 0, 'system', '表情、梗图、搞笑图', 4),
    (5, '产品', 0, 'system', '商品、摄影棚照片', 5),
    (6, '艺术', 0, 'system', '绘画、设计作品', 6),
    (7, '截图', 0, 'system', '屏幕截图、界面', 7),
    (8, '文档', 0, 'system', '文字、表格、证件', 8),
    (9, '其他', 0, 'system', '无法分类', 99)
ON CONFLICT (name) DO UPDATE SET 
    id = EXCLUDED.id,
    level = EXCLUDED.level, 
    source = EXCLUDED.source,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order;

COMMIT;

-- 验证结果
SELECT level, COUNT(*) as count, MIN(id) as min_id, MAX(id) as max_id 
FROM tags 
GROUP BY level 
ORDER BY level;
