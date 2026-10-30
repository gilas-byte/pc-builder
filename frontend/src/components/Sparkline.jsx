import { useI18n } from '../i18n/index.jsx'

// Mini-gráfico de 30 dias em SVG puro (sem biblioteca).
export default function Sparkline({ values = [], width = 120, height = 32, highlight = false }) {
  const { t } = useI18n()
  if (values.length < 2) {
    return <span className="spark-empty">{t('spark.short')}</span>
  }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = width / (values.length - 1)
  const pts = values.map((v, i) => [i * step, height - 3 - ((v - min) / span) * (height - 6)])
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const [lx, ly] = pts[pts.length - 1]
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label={t('spark.aria', { days: values.length })}>
      <path d={`${d} L${width},${height} L0,${height} Z`} className="spark-area" />
      <path d={d} className={highlight ? 'spark-line hot' : 'spark-line'} />
      <circle cx={lx} cy={ly} r="2.5" className={highlight ? 'spark-dot hot' : 'spark-dot'} />
    </svg>
  )
}
