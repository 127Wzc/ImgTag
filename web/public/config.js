// 运行时配置入口（兜底，防 404）
// - 纯静态托管：此文件确保 /config.js 永远存在
// - 容器/动态平台：可由启动脚本或 Vercel Function 覆盖同路径 /config.js 注入运行时环境变量
window.__IMGTAG_CONFIG__ = window.__IMGTAG_CONFIG__ || {}
