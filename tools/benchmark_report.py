"""Run inside Blender to compare shared-snapshot report generation with three-read baseline."""
import sys, inspect, time, statistics, tempfile, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optical_alignment_sim as addon
addon.register()
from optical_alignment_sim import optics_api as api, tracer
api.build_example('surface_figure')
source=inspect.getsource(api.export_report)
source=source.replace('def export_report(', 'def _legacy_export(').replace('    segments = list(tracer.cached_segments)\n    dash = _inspect_all_from_segments(_scene(), segments)\n    diag = {"diagnostics": state.get("diagnostics", [])}', '    dash = inspect_all() or {}\n    diag = diagnose() or {}')
ns=dict(api.__dict__);exec(source,ns);old=ns['_legacy_export']
path=str(Path(tempfile.gettempdir())/'optics-perf-report.html')
old(path);expected=Path(path).read_text();api.export_report(path);assert expected==Path(path).read_text()
results={}
for name,fn in [('before',old),('after',api.export_report)]:
    original=tracer.trace_scene;calls=[]
    def counted(*a,**k):calls.append(1);return original(*a,**k)
    tracer.trace_scene=counted
    fn(path)
    tracer.trace_scene=original
    times=[]
    for _ in range(15):
        start=time.perf_counter();fn(path);times.append((time.perf_counter()-start)*1000)
    results[name]={'trace_calls':len(calls),'median_ms':statistics.median(times),'samples_ms':times}
results['html_equal']=True
(Path(tempfile.gettempdir()) / 'optics-report-optimization.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results),flush=True)
