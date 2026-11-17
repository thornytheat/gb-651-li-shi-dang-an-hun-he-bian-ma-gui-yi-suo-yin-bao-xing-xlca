from pathlib import Path
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
PAGES = [('/intake', 'm1_intake.html', '文件采信'), ('/encoding', 'm2_encoding.html', '编码判定'), ('/fields', 'm3_fields.html', '字段保形'), ('/content', 'm4_content.html', '内容归一'), ('/reconcile', 'm5_reconcile.html', '索引对账'), ('/runs', 'm6_runs.html', '批次导出')]
