#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文本向量嵌入工具
使用BAAI/bge-small-zh-v1.5模型生成中文文本的向量表示
"""

import torch
from transformers import AutoTokenizer, AutoModel
import numpy as np
import os
import time
from pathlib import Path
from logging_config import get_logger, get_perf_logger
from config import MODEL_NAME, MODEL_DIR

# 获取日志记录器
logger = get_logger(__name__)
perf_logger = get_perf_logger()

class TextEmbedding:
    """文本向量嵌入类"""
    
    def __init__(self, model_name=MODEL_NAME):
        """初始化模型
        
        Args:
            model_name: 模型名称，默认使用配置中的MODEL_NAME
        """
        logger.info(f"初始化TextEmbedding，模型名称: {model_name}")
        start_time = time.time()
        
        # 设置本地模型路径
        local_model_path = f"{MODEL_DIR}/{model_name}"
        
        try:
            # 检查目录是否存在，不存在则创建
            if not os.path.exists(local_model_path):
                logger.info(f"本地模型不存在，从Hugging Face下载: {model_name}")
                Path(local_model_path).mkdir(parents=True, exist_ok=True)
                
                # 从Hugging Face下载模型
                self.tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=MODEL_DIR)
                self.model = AutoModel.from_pretrained(model_name, cache_dir=MODEL_DIR)
                
                # 保存模型到本地路径
                self.tokenizer.save_pretrained(local_model_path)
                self.model.save_pretrained(local_model_path)
            else:
                logger.info(f"从本地加载模型: {local_model_path}")
                self.tokenizer = AutoTokenizer.from_pretrained(local_model_path)
                self.model = AutoModel.from_pretrained(local_model_path)
            
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model.to(self.device)
            
            load_time = time.time() - start_time
            logger.info(f"模型加载完成，使用设备: {self.device}")
            perf_logger.info(f"模型加载耗时: {load_time:.2f}秒")
        except Exception as e:
            logger.error(f"模型加载失败: {str(e)}")
            raise
    
    def get_embedding(self, text, normalize=True):
        """获取文本的向量嵌入
        
        Args:
            text: 输入文本
            normalize: 是否对向量进行归一化处理
            
        Returns:
            文本的向量表示（numpy数组）
        """
        start_time = time.time()
        logger.debug(f"生成文本向量: '{text[:30]}...'")
        
        try:
            # 对文本进行编码
            encoded_input = self.tokenizer(
                text, 
                padding=True, 
                truncation=True, 
                max_length=512, 
                return_tensors='pt'
            ).to(self.device)
            
            # 生成向量表示
            with torch.no_grad():
                model_output = self.model(**encoded_input)
                # 使用[CLS]标记的输出作为文本表示
                embedding = model_output.last_hidden_state[:, 0, :].cpu().numpy()
            
            # 归一化处理
            if normalize:
                embedding = embedding / np.linalg.norm(embedding, axis=1, keepdims=True)
            
            process_time = time.time() - start_time
            perf_logger.info(f"文本向量生成: {len(text)}字符，耗时: {process_time:.4f}秒")
            
            return embedding[0]  # 返回第一个文本的向量表示
        except Exception as e:
            logger.error(f"向量生成失败: {str(e)}")
            raise
    
    def get_embedding_with_tags(self, text, tags, tag_weight=0.5, normalize=True):
        """结合文本和标签生成向量表示（分别计算再合并）
        
        Args:
            text: 文本描述
            tags: 标签列表
            tag_weight: 标签在最终向量中的权重 (0-1之间)
            normalize: 是否对向量进行归一化处理
            
        Returns:
            结合文本和标签的向量表示（numpy数组）
        """
        start_time = time.time()
        logger.debug(f"生成文本+标签向量: '{text[:30]}...', 标签: {tags}")
        
        try:
            # 将标签列表转换为文本
            tags_text = ",".join(tags) if isinstance(tags, list) else tags
            
            # 分别获取文本和标签的向量表示
            text_embedding = self.get_embedding(text, normalize=False)
            tags_embedding = self.get_embedding(tags_text, normalize=False)
            
            # 按权重结合两个向量
            combined_embedding = (1 - tag_weight) * text_embedding + tag_weight * tags_embedding
            
            # 归一化处理
            if normalize:
                combined_embedding = combined_embedding / np.linalg.norm(combined_embedding)
            
            process_time = time.time() - start_time
            perf_logger.info(f"文本+标签向量生成: {len(text)}字符, {len(tags) if isinstance(tags, list) else 1}个标签, 耗时: {process_time:.4f}秒")
            
            return combined_embedding
        except Exception as e:
            logger.error(f"向量生成失败: {str(e)}")
            raise

    def get_embedding_combined(self, text, tags, normalize=True):
        """将文本和标签组合后生成向量表示（直接组合后计算）
        
        Args:
            text: 文本描述
            tags: 标签列表
            normalize: 是否对向量进行归一化处理
            
        Returns:
            组合后的向量表示（numpy数组）
        """
        start_time = time.time()
        logger.debug(f"生成组合文本向量: '{text[:30]}...', 标签: {tags}")
        
        try:
            # 将标签列表转换为文本
            tags_text = ", ".join(tags) if isinstance(tags, list) else tags
            
            # 组合文本和标签
            combined_text = f"{text} 标签: {tags_text}"
            
            # 直接获取组合文本的向量表示
            embedding = self.get_embedding(combined_text, normalize=normalize)
            
            process_time = time.time() - start_time
            perf_logger.info(f"组合文本向量生成: {len(combined_text)}字符, 耗时: {process_time:.4f}秒")
            
            return embedding
        except Exception as e:
            logger.error(f"向量生成失败: {str(e)}")
            raise


if __name__ == "__main__":
    """示例用法"""
    # 初始化文本向量化工具
    text_embedding = TextEmbedding()
    
    # 单个文本向量化示例
    text = "这是一段需要转换为向量的中文文本"
    embedding = text_embedding.get_embedding(text)
    print(f"文本: '{text}'")
    print(f"向量维度: {embedding.shape}")
    print(f"向量前5个元素: {embedding[:5]}")
    
    # 结合标签的向量化示例
    tags = ["示例", "测试", "向量"]
    combined_embedding = text_embedding.get_embedding_combined(text, tags)
    print(f"\n文本+标签: '{text}' + {tags}")
    print(f"向量维度: {combined_embedding.shape}")
    print(f"向量前5个元素: {combined_embedding[:5]}")
    
    # 计算相似度示例
    from sklearn.metrics.pairwise import cosine_similarity
    similarity = cosine_similarity([embedding], [combined_embedding])[0][0]
    print(f"\n两个向量的余弦相似度: {similarity:.4f}") 