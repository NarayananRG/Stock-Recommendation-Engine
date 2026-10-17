import os
from pathlib import Path
root=Path(os.environ["SRE_ENGINE_ROOT"])/"modern_ui/frontend"
app=root/"app.js"
s=app.read_text(encoding="utf-8")
if "function forecastDiagnosticInline(item){" in s or "function forecastDiagnosticHtml(item){" in s:
    raise RuntimeError("Diagnostic already applied")
# Native 0.14.3 replaces renderOpportunityTable, so the old liveEvidenceHtml call is no longer present.
# Insert a visible diagnostic into the final table's Evidence cell, with one exact verified anchor.
anchor='<small>${escapeHtml(decisionBasisText(x))}</small>'
if s.count(anchor) != 1:
    raise RuntimeError(f"Final opportunity-table diagnostic insertion anchor must occur once, found {s.count(anchor)}")
s=s.replace(anchor,anchor+'${forecastDiagnosticInline(i)}',1)
s+="""

function forecastDiagnosticInline(item){
  const d=item&&item.forecast_diagnostic;
  if(!d)return '';
  const flags=Array.isArray(d.flags)?d.flags:[];
  if(d.conflict_severity!=='MATERIAL'&&d.conflict_severity!=='DIRECTIONAL'&&!flags.includes('LOW_POSITIVE_ANALOGUE_RATE'))return '';
  return '<small class="forecast-conflict-flag">Forecast evidence: '+escapeHtml(d.conflict_severity||'UNKNOWN')+'; review conflicting or weak short-term signals.</small>';
}
function forecastDiagnosticHtml(item){
  const d=item&&item.forecast_diagnostic;
  if(!d||typeof d!=='object')return '';
  const flags=Array.isArray(d.flags)?d.flags:[];
  const severity=String(d.conflict_severity||'UNKNOWN');
  const serious=severity==='MATERIAL'||flags.includes('LOW_POSITIVE_ANALOGUE_RATE');
  const pct=x=>typeof x==='number'&&Number.isFinite(x)?(x*100).toFixed(2)+'%':'not verified';
  const note=serious?'Conflicting or weak short-term evidence; review before relying on this BUY label.':
    severity==='DIRECTIONAL'?'Forecast direction differs between two methods. Review evidence.':
    'The legacy forecast and technical analogues use different models.';
  const review=flags.includes('RECOMMENDATION_REVIEW_HORIZON_DIFFERS_FROM_FORECAST');
  return '<section role="note" class="forecast-disagreement" style="border:1px solid #999;border-radius:8px;padding:10px;margin:10px 0">'+
    '<strong>Forecast evidence: '+escapeHtml(severity)+'</strong>'+
    '<p>Legacy forecast: '+escapeHtml(pct(d.legacy_expected_return_fraction))+
    '; technical analogue median: '+escapeHtml(pct(d.technical_analogue_median_fraction))+'.</p>'+
    '<p>'+escapeHtml(note)+'</p>'+
    (review?'<small>Review horizon differs from forecast horizon.</small>':'')+
    '<small>Diagnostic only. Does not change BUY rules. Forecast calibration is not established.</small></section>';
}
"""
app.write_text(s,encoding="utf-8")
print("FORECAST DIAGNOSTIC UI APPLIED")
