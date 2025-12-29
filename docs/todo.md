# 存储同步功能 TODO

## 当前状态
- ✅ Local → S3 同步：可用
- ⛔ S3 → Local 同步：暂不支持（需要更多功能）
- ⛔ S3 → S3 同步：暂不支持

## 待完成功能

### 1. 基础架构问题
- [ ] **文件命名不统一**
  - `upload_service` 使用 UUID 命名
  - `storage_service.generate_object_key` 使用 hash 命名
  - 需要统一为 hash 命名以支持去重和恢复

### 2. S3 → Local 同步前置条件
- [ ] **下载到本地目录**
  - 当前只创建 location 记录，不下载物理文件
  - 需要实现 S3 文件下载到 local uploads 目录
  
- [ ] **文件名映射**
  - S3 的 object_key (hash) 与 local 文件名 (UUID) 不一致
  - 需要在 sync 时保持文件名映射或统一

### 3. 数据安全功能
- [ ] **端点数据清理 API**
  - `DELETE /storage/endpoints/{id}/locations`
  - 只删除某端点的 location 记录，不删物理文件
  - 前提：需确认其他端点有备份

- [ ] **重建扫描功能**
  - 扫描 local 目录重建丢失的 location 记录
  - 通过计算文件 hash 匹配 images 表

### 4. 前端限制
- [ ] 同步对话框限制目标端点选择
- [ ] 添加同步方向说明提示

---

## 已完成修复
- [x] 流式同步路径触发后台任务
- [x] 任务恢复逻辑支持 `storage_sync` 类型
- [x] 负载均衡权重选择实现
- [x] 分页查询优化内存使用
