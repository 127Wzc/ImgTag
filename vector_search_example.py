#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
向量数据库相似度搜索示例
"""

import time
from pg_vector_operations import PGVectorDB
from text_embedding import TextEmbedding
from logging_config import get_logger, get_perf_logger
from config import DEFAULT_SAMPLE_COUNT, DEFAULT_SEARCH_LIMIT, DEFAULT_SIMILARITY_THRESHOLD

# 获取日志记录器
logger = get_logger(__name__)
perf_logger = get_perf_logger()

def generate_sample_data(db, num_samples=DEFAULT_SAMPLE_COUNT):
    """生成并插入示例数据
    
    Args:
        db: PGVectorDB实例
        num_samples: 样本数量
    """
    logger.info(f"生成{num_samples}条示例数据")
    start_time = time.time()
    
    # 初始化文本向量化工具
    text_embedding = TextEmbedding()
    
    # 示例标签集合
    tag_sets = [
        ["自然", "山脉", "日落"],
        ["城市", "建筑", "夜景"],
        ["动物", "野生", "哺乳动物"],
        ["食物", "甜点", "水果"],
        ["人物", "肖像", "微笑"],
        ["科技", "电子", "设备"],
        ["艺术", "绘画", "抽象"],
        ["交通", "汽车", "道路"],
        ["运动", "足球", "比赛"],
        ["旅行", "景点", "度假"]
    ]
    
    # 对应的描述文本
    descriptions = [
        "壮丽的自然风景，包括高耸的山脉和美丽的日落景观",
        "现代化的城市建筑和璀璨的夜景灯光",
        "野生动物园中各种可爱的哺乳动物",
        "美味的甜点和新鲜的水果拼盘",
        "微笑的人物肖像照片",
        "最新的电子科技设备和产品",
        "抽象艺术绘画作品展示",
        "各种汽车在道路上行驶的场景",
        "激烈的足球比赛现场",
        "著名旅游景点和度假胜地"
    ]
    
    total_vector_time = 0
    total_db_time = 0
    
    # 生成示例数据
    for i in range(num_samples):
        # 选择标签集和描述
        tag_index = i % len(tag_sets)
        tags = tag_sets[tag_index]
        description = descriptions[tag_index]
        
        # 生成URL
        image_url = f"https://example.com/image_{i+1}.jpg"
        
        # 使用文本和标签结合生成向量
        vector_start = time.time()
        embedding = text_embedding.get_embedding_combined(description, tags).tolist()
        vector_time = time.time() - vector_start
        total_vector_time += vector_time
        
        # 插入数据库，包括描述文本
        db_start = time.time()
        db.insert_image(image_url, tags, embedding, description)
        db_time = time.time() - db_start
        total_db_time += db_time
        
        logger.info(f"已处理 {i+1}/{num_samples} 条数据")
    
    total_time = time.time() - start_time
    
    # 记录整体性能数据
    perf_logger.info(f"示例数据生成完成: {num_samples}条，总耗时: {total_time:.2f}秒")
    perf_logger.info(f"向量生成平均耗时: {total_vector_time/num_samples:.4f}秒/条")
    perf_logger.info(f"数据库插入平均耗时: {total_db_time/num_samples:.4f}秒/条")


def main():
    """主函数"""
    logger.info("开始运行向量数据库搜索示例")
    
    # 创建数据库连接
    db = PGVectorDB()
    
    # 表初始化已在PGVectorDB的初始化方法中自动完成
    # 检查数据库中是否已有数据
    count = db.count_images()
    if count < 10:
        # 生成示例数据
        generate_sample_data(db)
    
    logger.info("=== 开始向量数据库搜索测试 ===")
    
    # 1. 通过标签搜索
    logger.info("执行标签搜索")
    tag_search_start = time.time()
    
    tag_results = db.search_by_tags(["自然", "山脉"], limit=3)
    
    tag_search_time = time.time() - tag_search_start
    perf_logger.info(f"标签搜索耗时: {tag_search_time:.4f}秒")
    
    for i, img in enumerate(tag_results):
        logger.info(f"标签搜索结果 {i+1}: {img['image_url']}")
        logger.info(f"标签: {img['tags']}")
        logger.info(f"描述: {img['description']}")
    
    # 2. 向量相似度搜索
    logger.info("执行向量相似度搜索")
    
    # 初始化文本向量化工具
    text_embedding = TextEmbedding()
    
    # 使用文本和标签结合生成查询向量
    query_text = "美丽的自然风景和山脉"
    query_tags = ["自然", "风景", "山脉"]
    
    vector_gen_start = time.time()
    query_vector = text_embedding.get_embedding_combined(query_text, query_tags).tolist()
    vector_gen_time = time.time() - vector_gen_start
    
    perf_logger.info(f"查询向量生成耗时: {vector_gen_time:.4f}秒")
    logger.info(f"查询: '{query_text}', 标签: {query_tags}")
    
    # 执行相似度搜索
    vector_search_start = time.time()
    similar_results = db.search_similar_vectors(
        query_vector, 
        limit=5,
        threshold=DEFAULT_SIMILARITY_THRESHOLD
    )
    vector_search_time = time.time() - vector_search_start
    
    perf_logger.info(f"向量搜索耗时: {vector_search_time:.4f}秒")
    
    for i, img in enumerate(similar_results):
        logger.info(f"相似度搜索结果 {i+1}: {img['image_url']}")
        logger.info(f"标签: {img['tags']}, 相似度: {img['similarity']:.4f}")
        logger.info(f"描述: {img['description']}")
    
    # 性能总结
    perf_logger.info("=== 性能统计 ===")
    perf_logger.info(f"向量生成: {vector_gen_time:.4f}秒")
    perf_logger.info(f"标签搜索: {tag_search_time:.4f}秒, 结果数: {len(tag_results)}")
    perf_logger.info(f"向量搜索: {vector_search_time:.4f}秒, 结果数: {len(similar_results)}")
    
    logger.info("搜索示例完成")


if __name__ == "__main__":
    main() 