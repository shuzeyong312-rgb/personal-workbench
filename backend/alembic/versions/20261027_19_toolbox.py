"""Create the toolbox catalog."""
from alembic import op
import sqlalchemy as sa

revision = "20261027_19"
down_revision = "20261023_18"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "toolbox_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("builtin_key", sa.String(32), unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(300), nullable=False, unique=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("url", sa.String(2048), unique=True),
        sa.Column("favorite", sa.Boolean, nullable=False),
        sa.CheckConstraint("(kind = 'builtin' AND builtin_key IS NOT NULL AND url IS NULL) OR (kind = 'site' AND builtin_key IS NULL AND url IS NOT NULL)", name="ck_toolbox_item_kind"),
    )
    op.bulk_insert(table, [
        {"kind": "builtin", "builtin_key": "compress", "name": "图片压缩", "name_key": "图片压缩", "category": "图片处理", "description": "单张或批量缩小图片体积", "url": None, "favorite": True},
        {"kind": "builtin", "builtin_key": "resize", "name": "图片尺寸修改", "name_key": "图片尺寸修改", "category": "图片处理", "description": "批量调整图片像素尺寸", "url": None, "favorite": False},
        {"kind": "site", "builtin_key": None, "name": "iLovePDF", "name_key": "ilovepdf", "category": "PDF 工具", "description": "PDF 合并、拆分、压缩和格式转换", "url": "https://www.ilovepdf.com/zh-cn", "favorite": True},
    ])


def downgrade():
    op.drop_table("toolbox_items")
