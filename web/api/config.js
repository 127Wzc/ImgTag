export default function handler(req, res) {
  const payload = {}
  const keys = Object.keys(process.env)
    .filter((k) => k.startsWith('VITE_'))
    .sort()

  for (const key of keys) {
    payload[key] = process.env[key] ?? null
  }

  res.setHeader('Content-Type', 'application/javascript; charset=utf-8')
  res.setHeader('Cache-Control', 'no-store, max-age=0')
  res.setHeader('Pragma', 'no-cache')
  res.setHeader('X-Content-Type-Options', 'nosniff')

  res.status(200).send(`window.__IMGTAG_CONFIG__ = ${JSON.stringify(payload)};\n`)
}
