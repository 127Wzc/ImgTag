## **项目背景:** 

​	起初是在整理表情包给角色扮演的机器人匹配合适语境的表情包麻烦，自己手动给图片打标较慢切难以管理。这两周空闲时间在ai加持下写了这个项目(100% ai生成哦，人工只做指挥)。



> [!NOTE]
>
> 理论上可以作为统一图床甚至介入ai更形象的发图，不局限于表情包。



## 项目主要功能：

- 基于视频模型和自定义提示词自动对图片进行打标，然后向量化存储，提供多维度的筛选。

- 支持s3兼容端点存储，并支持设置备份端点自动同步备份，对存储端点进行负载均衡。

- 简单的多用户管理，方便多人合作上传

- 图片区分公开和个人可见(管理员可见所有)

  详情可参考https://github.com/127Wzc/ImgTag/blob/main/README.md

## 项目地址：

https://github.com/127Wzc/ImgTag

**项目体验地址：**https://img-tag.vercel.app   demo/demo123

## 项目功能截图预览:

1. 首页

![image-20260102150010644](../../../Library/Application Support/typora-user-images/image-20260102150010644.png)

2. 仪表盘![image-20260102150049948](../../../Library/Application Support/typora-user-images/image-20260102150049948.png)

3. 我的图库-这里提供多维筛选+批量操作

   ![image-20260102150229295](../../../Library/Application Support/typora-user-images/image-20260102150229295.png)

4. 图片探索(公开)- 提供多维搜索和向量搜索

   ![image-20260102150317476](../../../Library/Application Support/typora-user-images/image-20260102150317476.png)

   ![image-20260102150836191](../../../Library/Application Support/typora-user-images/image-20260102150836191.png)

5. 上传图片
   

6. 存储端点管理

![image-20260102151138867](../../../Library/Application Support/typora-user-images/image-20260102151138867.png)

![image-20260102151158144](../../../Library/Application Support/typora-user-images/image-20260102151158144.png)

7.标签管理，主分类标签提示词拿过去针对性提取相关关键字。

![image-20260102151342403](../../../Library/Application Support/typora-user-images/image-20260102151342403.png)

8.任务队列

对于批量、耗时的异步操作，比如图片分析、批量删除、同步、批量分析等可以看到在任务队列看到相关参数和操作对象及结果
![image-20260102151512267](../../../Library/Application Support/typora-user-images/image-20260102151512267.png)

9.系统设置

全局配置视觉模型相关内容、向量模型、以及用户管理和一些杂项配置

![image-20260102151548637](../../../Library/Application Support/typora-user-images/image-20260102151548637.png)