"""Runtime customization for UI text and QSS overrides."""
import json
import os
import re
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QInputDialog,
    QStatusBar,
    QSystemTrayIcon,
    QTextEdit,
    QWidget,
)


APP_NAME = 'FRESH'
TEXT_CONFIG_NAME = 'ui_text.json'
CUSTOM_QSS_NAME = 'custom.qss'

_TEXTS = {}
_COMPILED_TEMPLATES = []
_INSTALLED = False
_APPLYING_TEXT = False
_ORIGINALS = {}


DEFAULT_TEXTS = {
    'FRESH': 'FRESH',
    '文字': '文字',
    '截图': '截图',
    '文字文件': '文字文件',
    '全截图': '全截图',
    '活跃': '活跃',
    '归档': '归档',
    '活跃  ·  {count}': '活跃  ·  {count}',
    '归档  ·  {count}': '归档  ·  {count}',
    '＋  添加截图': '＋  添加截图',
    '＋  新建': '＋  新建',
    '⋯': '⋯',
    '更多': '更多',
    '搜索截图': '搜索截图',
    '搜索文字和文件': '搜索文字和文件',
    '全部分类': '全部分类',
    '时间线': '时间线',
    '框选截图': '框选截图',
    '选择图片文件...': '选择图片文件...',
    '框选截图失败': '框选截图失败',
    '无法获取屏幕截图。': '无法获取屏幕截图。',
    '请拖拽选择要保存的区域。按 Esc 取消。': '请拖拽选择要保存的区域。按 Esc 取消。',
    '查看所有已完成的事项': '查看所有已完成的事项',
    '未命名备忘录': '未命名备忘录',
    '开始记录...': '开始记录...',
    '加粗': '加粗',
    '斜体': '斜体',
    '下划线': '下划线',
    '项目符号列表': '项目符号列表',
    '清除格式': '清除格式',
    '新建备忘录': '新建备忘录',
    '没有附加文本': '没有附加文本',
    '昨天': '昨天',
    '周一': '周一',
    '周二': '周二',
    '周三': '周三',
    '周四': '周四',
    '周五': '周五',
    '周六': '周六',
    '周日': '周日',
    '粘贴 (Ctrl+V) 或拖入图片到此处': '粘贴 (Ctrl+V) 或拖入图片到此处',
    '备注…': '备注…',
    '图片不存在': '图片不存在',
    '无法加载': '无法加载',
    '无法加载图片': '无法加载图片',
    '查看大图': '查看大图',
    '归档照片': '归档照片',
    '取消归档照片': '取消归档照片',
    '已归档 · 点击取消': '已归档 · 点击取消',
    '归档这张照片': '归档这张照片',
    '{name}\n双击查看大图 · 右键更多': '{name}\n双击查看大图 · 右键更多',
    '保存为...': '保存为...',
    '保存为': '保存为',
    '在文件夹中显示': '在文件夹中显示',
    '从备忘录中移除': '从备忘录中移除',
    '文件不存在': '文件不存在',
    '原始图片已不存在。': '原始图片已不存在。',
    '保存失败': '保存失败',
    '适应窗口': '适应窗口',
    '100%': '100%',
    '完成了什么内容？': '完成了什么内容？',
    '这段内容会保存到照片归档记录，并显示在时间线里。': '这段内容会保存到照片归档记录，并显示在时间线里。',
    '无法预览': '无法预览',
    '填写后点击“归档照片”。': '填写后点击“归档照片”。',
    '分类': '分类',
    '选择或输入分类': '选择或输入分类',
    '置顶': '置顶',
    '取消置顶': '取消置顶',
    '已置顶': '已置顶',
    '已取消置顶': '已取消置顶',
    '例如：整理完登录页错误状态、标注了按钮位置、确认这张图的问题已经处理...': '例如：整理完登录页错误状态、标注了按钮位置、确认这张图的问题已经处理...',
    '取消': '取消',
    '没有匹配的备忘录': '没有匹配的备忘录',
    '换一个关键词或清除分类筛选。': '换一个关键词或清除分类筛选。',
    '当前搜索“{search}”，分类为“{category}”。': '当前搜索“{search}”，分类为“{category}”。',
    '当前搜索“{search}”。': '当前搜索“{search}”。',
    '当前分类为“{category}”。': '当前分类为“{category}”。',
    '清除筛选': '清除筛选',
    '新建备忘录': '新建备忘录',
    '归档里还没有内容': '归档里还没有内容',
    '截图归档后会出现在这里，也会按分类进入时间线。': '截图归档后会出现在这里，也会按分类进入时间线。',
    '查看时间线': '查看时间线',
    '回到活跃': '回到活跃',
    '开始收集截图': '开始收集截图',
    '拖入图片、粘贴截图，或点击添加截图。完成后可单张归档。': '拖入图片、粘贴截图，或点击添加截图。完成后可单张归档。',
    '添加截图': '添加截图',
    '— 没有备注 —': '— 没有备注 —',
    '打开所属备忘录': '打开所属备忘录',
    '取消归档': '取消归档',
    '打开备忘录': '打开备忘录',
    '归档备忘录': '归档备忘录',
    '时间线 · 归档': '时间线 · 归档',
    '暂无归档内容': '暂无归档内容',
    '{count} 张归档照片': '{count} 张归档照片',
    '{count} 条归档备忘录': '{count} 条归档备忘录',
    '还没有归档内容\n\n归档照片或备忘录后会出现在这里': '还没有归档内容\n\n归档照片或备忘录后会出现在这里',
    '#{category} 下还没有归档内容': '#{category} 下还没有归档内容',
    '未知日期': '未知日期',
    '文件查找设置': '文件查找设置',
    'Everything 加速（强烈推荐）': 'Everything 加速（强烈推荐）',
    'FRESH 优先用 Everything 的索引秒级定位文件，找不到再读 ADS 验证。\n只要 Everything 主程序在跑，自动启用 IPC 直连模式（无需 es.exe）。': 'FRESH 优先用 Everything 的索引秒级定位文件，找不到再读 ADS 验证。\n只要 Everything 主程序在跑，自动启用 IPC 直连模式（无需 es.exe）。',
    '启用 Everything 加速': '启用 Everything 加速',
    'es.exe 路径:': 'es.exe 路径:',
    '留空 = 自动检测（PATH + Everything 安装目录）': '留空 = 自动检测（PATH + Everything 安装目录）',
    '浏览...': '浏览...',
    '没装 es.exe？': '没装 es.exe？',
    '打开 voidtools 下载页面': '打开 voidtools 下载页面',
    '重新检测 es.exe': '重新检测 es.exe',
    '扫描范围': '扫描范围',
    '留空时自动扫描所有 NTFS 盘。指定后只在这些位置中查找（仅影响 os.walk 兜底；Everything 总是查询全盘索引）。': '留空时自动扫描所有 NTFS 盘。指定后只在这些位置中查找（仅影响 os.walk 兜底；Everything 总是查询全盘索引）。',
    '添加文件夹...': '添加文件夹...',
    '添加盘符...': '添加盘符...',
    '移除选中': '移除选中',
    '保存': '保存',
    '无可用盘': '无可用盘',
    '未检测到本地盘符。': '未检测到本地盘符。',
    '已全部添加': '已全部添加',
    '所有盘符都已在列表中。': '所有盘符都已在列表中。',
    '选择盘符': '选择盘符',
    '选择要添加的盘:': '选择要添加的盘:',
    '选择匹配的文件': '选择匹配的文件',
    '扫描到 {count} 个同名文件，请选择哪个是 "{attachment_name}"：': '扫描到 {count} 个同名文件，请选择哪个是 "{attachment_name}"：',
    '选定': '选定',
    '正在后台查找"{name}"...': '正在后台查找"{name}"...',
    '查找已移动的文件': '查找已移动的文件',
    '文件夹': '文件夹',
    '文件': '文件',
    '双击打开 · 右键更多': '双击打开 · 右键更多',
    '{name} ({kind})\n双击打开 · 右键更多': '{name} ({kind})\n双击打开 · 右键更多',
    '删除': '删除',
    '打开': '打开',
    '重新定位文件...': '重新定位文件...',
    '查找已移动的文件...': '查找已移动的文件...',
    '无法查找': '无法查找',
    '该附件加入时未生成追踪标记，无法定位。': '该附件加入时未生成追踪标记，无法定位。',
    '路径不存在': '路径不存在',
    '该文件夹已被移动或删除。': '该文件夹已被移动或删除。',
    '该附件文件已被移动或删除。': '该附件文件已被移动或删除。',
    '附件': '附件',
    '拖入文件或文件夹': '拖入文件或文件夹',
    '+': '+',
    '暂无附件,拖入文件或文件夹': '暂无附件,拖入文件或文件夹',
    '选择文件...': '选择文件...',
    '选择文件夹...': '选择文件夹...',
    '选择文件': '选择文件',
    '选择文件夹': '选择文件夹',
    '删除备忘录': '删除备忘录',
    '确定要把这条备忘录移到最近删除吗？之后仍可恢复。': '确定要把这条备忘录移到最近删除吗？之后仍可恢复。',
    '已移到最近删除': '已移到最近删除',
    '最近删除': '最近删除',
    '恢复': '恢复',
    '彻底删除': '彻底删除',
    '{count} 项可恢复': '{count} 项可恢复',
    '没有最近删除的项目': '没有最近删除的项目',
    '删除的备忘录、附件和截图会先保留在这里。': '删除的备忘录、附件和截图会先保留在这里。',
    '备忘录 · {title}': '备忘录 · {title}',
    '{kind} · {name}': '{kind} · {name}',
    '删除于 {time}': '删除于 {time}',
    '来自 {title} · 删除于 {time}': '来自 {title} · 删除于 {time}',
    '确定要彻底删除选中的项目吗？此操作无法撤销。': '确定要彻底删除选中的项目吗？此操作无法撤销。',
    '归档分类': '归档分类',
    '选择或输入分类:': '选择或输入分类:',
    '输入分类:': '输入分类:',
    '需要分类': '需要分类',
    '请填写归档分类。': '请填写归档分类。',
    '未找到': '未找到',
    '未在磁盘上找到与 "{name}" 匹配的文件。': '未在磁盘上找到与 "{name}" 匹配的文件。',
    '已找到': '已找到',
    '文件当前位置:\n{path}': '文件当前位置:\n{path}',
    '正在后台自动查找已移动的文件': '正在后台自动查找已移动的文件',
    '重点查找 {count} 项': '重点查找 {count} 项',
    '扫描中:\n{path}': '扫描中:\n{path}',
    'Everything 加速查找：{count} 个待找': 'Everything 加速查找：{count} 个待找',
    '后台扫描中：剩 {remaining} 个 · 已扫 {dirs_scanned} 目录': '后台扫描中：剩 {remaining} 个 · 已扫 {dirs_scanned} 目录',
    '已自动找回 {count} 个移动过的文件': '已自动找回 {count} 个移动过的文件',
    '{mode}：正在查找 {count} 个已移动的文件...': '{mode}：正在查找 {count} 个已移动的文件...',
    'Everything 加速': 'Everything 加速',
    '全盘扫描': '全盘扫描',
    '监听到 {names} 被复制/剪切，3 秒后自动定位新位置...': '监听到 {names} 被复制/剪切，3 秒后自动定位新位置...',
    '添加失败': '添加失败',
    '无法添加该附件。': '无法添加该附件。',
    '只能添加图片截图。': '只能添加图片截图。',
    '移除附件': '移除附件',
    '删除附件': '删除附件',
    '确定要把该附件移到最近删除吗？之后仍可恢复。': '确定要把该附件移到最近删除吗？之后仍可恢复。',
    '附件已移到最近删除': '附件已移到最近删除',
    '删除截图': '删除截图',
    '确定要把这张截图移到最近删除吗？之后仍可恢复。': '确定要把这张截图移到最近删除吗？之后仍可恢复。',
    '截图已移到最近删除': '截图已移到最近删除',
    '时间线 · 归档与完成': '时间线 · 归档与完成',
    '开机启动': '开机启动',
    '导出全部数据...': '导出全部数据...',
    '从备份导入...': '从备份导入...',
    '打开数据文件夹': '打开数据文件夹',
    '打开外观与文字配置': '打开外观与文字配置',
    '外观与文字配置...': '外观与文字配置...',
    '外观与文字配置': '外观与文字配置',
    '重新加载外观与文字': '重新加载外观与文字',
    '已重新加载外观与文字配置': '已重新加载外观与文字配置',
    '已保存外观与文字配置': '已保存外观与文字配置',
    '文字覆盖': '文字覆盖',
    '样式覆盖': '样式覆盖',
    '搜索界面文字': '搜索界面文字',
    '原文': '原文',
    '显示文字': '显示文字',
    '恢复选中默认': '恢复选中默认',
    '全部恢复默认': '全部恢复默认',
    '打开配置文件夹': '打开配置文件夹',
    '保存并应用': '保存并应用',
    '这里修改界面文字。左侧是程序原文，右侧是实际显示文字。': '这里修改界面文字。左侧是程序原文，右侧是实际显示文字。',
    '这里编辑 custom.qss，会追加在内置样式之后。保存后立即应用。': '这里编辑 custom.qss，会追加在内置样式之后。保存后立即应用。',
    '占位符缺失': '占位符缺失',
    '下面这些文字缺少必要占位符，保存后动态数字或名称可能无法显示：\n\n{items}\n\n仍然保存吗？': '下面这些文字缺少必要占位符，保存后动态数字或名称可能无法显示：\n\n{items}\n\n仍然保存吗？',
    '保存失败': '保存失败',
    '无法保存配置：{error}': '无法保存配置：{error}',
    '选择一条备忘录': '选择一条备忘录',
    '从左侧列表打开一条备忘录。': '从左侧列表打开一条备忘录。',
    '还没有备忘录': '还没有备忘录',
    '新建一条文字备忘录，或拖入文件作为附件。': '新建一条文字备忘录，或拖入文件作为附件。',
    '归档文字备忘录后会出现在这里；截图归档在全截图和时间线里查看。': '归档文字备忘录后会出现在这里；截图归档在全截图和时间线里查看。',
    '不支持': '不支持',
    '当前系统不支持此功能。': '当前系统不支持此功能。',
    '设置失败': '设置失败',
    '修改开机启动设置时出错。': '修改开机启动设置时出错。',
    '导出备份': '导出备份',
    '导出成功': '导出成功',
    '导出失败': '导出失败',
    '选择导入方式': '选择导入方式',
    '请选择导入方式': '请选择导入方式',
    '合并 — 将备份中的备忘录追加到现有数据中\n替换 — 清除当前所有数据,完全用备份替换': '合并 — 将备份中的备忘录追加到现有数据中\n替换 — 清除当前所有数据,完全用备份替换',
    '合并': '合并',
    '替换': '替换',
    '导入备份': '导入备份',
    '导入成功': '导入成功',
    '导入失败': '导入失败',
    '备份文件中缺少 data.json': '备份文件中缺少 data.json',
    '备份文件格式错误': '备份文件格式错误',
    'FRESH 已最小化到系统托盘': 'FRESH 已最小化到系统托盘',
    '点击托盘图标可重新打开。右键图标可退出。': '点击托盘图标可重新打开。右键图标可退出。',
    '显示 FRESH': '显示 FRESH',
    '快速新建文字': '快速新建文字',
    '快速框选截图': '快速框选截图',
    '保存剪贴板图片': '保存剪贴板图片',
    '剪贴板里没有图片': '剪贴板里没有图片',
    '没有可保存的剪贴板图片。': '没有可保存的剪贴板图片。',
    '已保存剪贴板图片': '已保存剪贴板图片',
    '剪贴板图片已保存到截图工作区。': '剪贴板图片已保存到截图工作区。',
    '退出 FRESH': '退出 FRESH',
}


DEFAULT_CUSTOM_QSS = """/*
FRESH custom.qss

修改这个文件后，在 FRESH 的「更多」菜单里点击「重新加载外观与文字」，
或重启软件生效。

常用选择器：
  #new_button                顶部新建/添加按钮
  #more_button               更多按钮
  #search_box                搜索框
  #view_btn_left/right       活跃/归档切换
  #mode_btn_left/right       文字/截图切换
  #timeline_btn              时间线按钮
  #title_input               标题输入框
  #note_category_combo       备忘录分类下拉框
  #content_edit              正文编辑器
  #attachment_bar            底部附件栏
  #screenshot_thumb          截图卡片

示例：

#new_button {
    background: #0F766E;
    border-radius: 6px;
}

#title_input {
    font-size: 24px;
}
*/
"""


class _TextRefreshFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QWidget):
            QTimer.singleShot(0, lambda w=obj: apply_text_overrides(w))
        return False


def customization_dir():
    appdata = os.getenv('APPDATA') or str(Path.home())
    return Path(appdata) / APP_NAME


def ensure_custom_files():
    directory = customization_dir()
    directory.mkdir(parents=True, exist_ok=True)

    text_file = directory / TEXT_CONFIG_NAME
    if not text_file.exists():
        data = {
            '_说明': [
                '只修改右侧 value，不要修改左侧 key。',
                '支持 {count}、{name} 这类占位符；如果 value 里需要显示变量，请保留对应占位符。',
                '修改后在 FRESH 的“更多”菜单点击“重新加载外观与文字”，或重启软件。',
            ],
            'texts': DEFAULT_TEXTS,
        }
        text_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        _ensure_text_file_has_defaults(text_file)

    qss_file = directory / CUSTOM_QSS_NAME
    if not qss_file.exists():
        qss_file.write_text(DEFAULT_CUSTOM_QSS, encoding='utf-8')

    return directory


def _ensure_text_file_has_defaults(text_file):
    try:
        data = json.loads(text_file.read_text(encoding='utf-8-sig'))
    except Exception:
        return
    if not isinstance(data, dict):
        return

    texts = data.get('texts')
    if isinstance(texts, dict):
        target = texts
    else:
        target = data

    changed = False
    for key, value in DEFAULT_TEXTS.items():
        if key not in target:
            target[key] = value
            changed = True

    if changed:
        try:
            text_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass


def text_config_path():
    return ensure_custom_files() / TEXT_CONFIG_NAME


def custom_qss_path():
    return ensure_custom_files() / CUSTOM_QSS_NAME


def load_text_overrides():
    global _TEXTS, _COMPILED_TEMPLATES
    ensure_custom_files()
    text_file = text_config_path()
    texts = dict(DEFAULT_TEXTS)
    try:
        data = json.loads(text_file.read_text(encoding='utf-8-sig'))
        custom = data.get('texts', data) if isinstance(data, dict) else {}
        if isinstance(custom, dict):
            for key, value in custom.items():
                if key.startswith('_'):
                    continue
                if isinstance(key, str) and isinstance(value, str):
                    texts[key] = value
    except Exception:
        pass

    _TEXTS = texts
    _COMPILED_TEMPLATES = [
        (_compile_template_pattern(key), value)
        for key, value in texts.items()
        if _is_template(key) and key != value
    ]


def reload_customization():
    load_text_overrides()


def load_text_config_values():
    ensure_custom_files()
    values = dict(DEFAULT_TEXTS)
    try:
        data = json.loads(text_config_path().read_text(encoding='utf-8-sig'))
        custom = data.get('texts', data) if isinstance(data, dict) else {}
        if isinstance(custom, dict):
            for key, value in custom.items():
                if isinstance(key, str) and isinstance(value, str) and not key.startswith('_'):
                    values[key] = value
    except Exception:
        pass
    return values


def save_text_config_values(values):
    ensure_custom_files()
    text_file = text_config_path()
    try:
        data = json.loads(text_file.read_text(encoding='utf-8-sig'))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    texts = data.get('texts')
    if not isinstance(texts, dict):
        texts = {}
    merged = {
        key: value
        for key, value in texts.items()
        if isinstance(key, str) and isinstance(value, str) and not key.startswith('_')
    }
    for key, default in DEFAULT_TEXTS.items():
        value = values.get(key, default) if isinstance(values, dict) else default
        merged[key] = value if isinstance(value, str) else default

    data['_说明'] = [
        '只修改右侧 value，不要修改左侧 key。',
        '支持 {count}、{name} 这类占位符；如果 value 里需要显示变量，请保留对应占位符。',
        '修改后在 FRESH 的“更多”菜单点击“重新加载外观与文字”，或重启软件。',
    ]
    data['texts'] = merged
    text_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    load_text_overrides()


def load_custom_qss_text():
    ensure_custom_files()
    try:
        return custom_qss_path().read_text(encoding='utf-8-sig')
    except Exception:
        return DEFAULT_CUSTOM_QSS


def save_custom_qss_text(text):
    ensure_custom_files()
    custom_qss_path().write_text(text or '', encoding='utf-8')


def customized_stylesheet(base_style):
    ensure_custom_files()
    try:
        custom = custom_qss_path().read_text(encoding='utf-8-sig')
    except Exception:
        custom = ''
    if custom.strip():
        return base_style.rstrip() + '\n\n/* === user custom.qss === */\n' + custom
    return base_style


def tr(text, **kwargs):
    if text is None:
        return text
    source = str(text)
    if kwargs:
        try:
            source = source.format(**kwargs)
        except Exception:
            pass
    return translate_text(source)


def translate_text(text):
    if not isinstance(text, str) or not text:
        return text
    exact = _TEXTS.get(text)
    if exact is not None:
        return exact
    for pattern, template in _COMPILED_TEMPLATES:
        match = pattern.fullmatch(text)
        if not match:
            continue
        try:
            return template.format(**match.groupdict())
        except Exception:
            return template
    return text


def install_text_overrides(app):
    global _INSTALLED
    ensure_custom_files()
    load_text_overrides()
    if _INSTALLED:
        return
    _INSTALLED = True

    _patch_text_setter(QLabel, 'setText', 'text')
    _patch_text_setter(QPushButton, 'setText', 'text')
    _patch_text_setter(QCheckBox, 'setText', 'text')
    _patch_text_setter(QGroupBox, 'setTitle', 'title')
    _patch_text_setter(QWidget, 'setWindowTitle', 'windowTitle')
    _patch_text_setter(QWidget, 'setToolTip', 'toolTip')
    _patch_text_setter(QLineEdit, 'setPlaceholderText', 'placeholderText')
    _patch_text_setter(QTextEdit, 'setPlaceholderText', 'placeholderText')
    _patch_text_setter(QAction, 'setText', 'text')
    _patch_text_setter(QAction, 'setToolTip', 'toolTip')
    _patch_text_setter(QProgressDialog, 'setLabelText', 'labelText')
    _patch_text_setter(QStatusBar, 'showMessage', 'message', duration_index=1)
    _patch_text_setter(QMessageBox, 'setText', 'text')
    _patch_text_setter(QMessageBox, 'setInformativeText', 'informativeText')
    _patch_text_setter(QSystemTrayIcon, 'setToolTip', 'toolTip')
    _patch_constructor(QLabel, 'text', 0)
    _patch_constructor(QPushButton, 'text', 0)
    _patch_constructor(QCheckBox, 'text', 0)
    _patch_constructor(QGroupBox, 'title', 0)
    _patch_progress_dialog_constructor()
    _patch_menu_add_action()
    _patch_messagebox_add_button()
    _patch_combo_box()
    _patch_static_dialogs()
    _patch_tray_message()

    if app is not None:
        app._fresh_text_refresh_filter = _TextRefreshFilter(app)
        app.installEventFilter(app._fresh_text_refresh_filter)


def apply_text_overrides(root=None):
    app = QApplication.instance()
    roots = []
    if root is not None:
        roots.append(root)
    elif app is not None:
        roots.extend(app.topLevelWidgets())

    for widget in roots:
        _apply_to_object(widget)
        if isinstance(widget, QWidget):
            for child in widget.findChildren(QObject):
                _apply_to_object(child)


def _is_template(text):
    return bool(re.search(r'\{[A-Za-z_][A-Za-z0-9_]*\}', text))


def _compile_template_pattern(template):
    parts = []
    last = 0
    seen = set()
    for match in re.finditer(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', template):
        name = match.group(1)
        parts.append(re.escape(template[last:match.start()]))
        if name in seen:
            parts.append(fr'(?P={name})')
        else:
            parts.append(fr'(?P<{name}>.+?)')
            seen.add(name)
        last = match.end()
    parts.append(re.escape(template[last:]))
    return re.compile(''.join(parts), re.S)


def _source_prop(prop_name):
    return f'freshSource_{prop_name}'


def _remember_source(obj, prop_name, text):
    if _APPLYING_TEXT or not isinstance(text, str):
        return
    try:
        obj.setProperty(_source_prop(prop_name), text)
    except Exception:
        pass


def _read_source(obj, prop_name):
    try:
        return obj.property(_source_prop(prop_name))
    except Exception:
        return None


def _call_original(cls, method_name, obj, *args):
    original = _ORIGINALS.get((cls, method_name)) or getattr(cls, method_name)
    return original(obj, *args)


def _patch_text_setter(cls, method_name, prop_name, duration_index=None):
    original = getattr(cls, method_name, None)
    if original is None:
        return
    _ORIGINALS[(cls, method_name)] = original

    def wrapped(self, text='', *args, **kwargs):
        source = text
        if isinstance(source, str):
            _remember_source(self, prop_name, source)
            text = translate_text(source)
        return original(self, text, *args, **kwargs)

    try:
        setattr(cls, method_name, wrapped)
    except Exception:
        _ORIGINALS.pop((cls, method_name), None)


def _patch_constructor(cls, prop_name, text_index):
    original = getattr(cls, '__init__', None)
    if original is None:
        return
    _ORIGINALS[(cls, '__init__', prop_name)] = original

    def wrapped(self, *args, **kwargs):
        args = list(args)
        source = None
        if len(args) > text_index and isinstance(args[text_index], str):
            source = args[text_index]
            args[text_index] = translate_text(source)
        original(self, *args, **kwargs)
        if source is not None:
            _remember_source(self, prop_name, source)

    try:
        setattr(cls, '__init__', wrapped)
    except Exception:
        _ORIGINALS.pop((cls, '__init__', prop_name), None)


def _patch_progress_dialog_constructor():
    original = getattr(QProgressDialog, '__init__', None)
    if original is None:
        return
    _ORIGINALS[(QProgressDialog, '__init__', 'progress')] = original

    def wrapped(self, *args, **kwargs):
        args = list(args)
        sources = {}
        for index, prop_name in ((0, 'labelText'), (1, 'cancelButtonText')):
            if len(args) > index and isinstance(args[index], str):
                sources[prop_name] = args[index]
                args[index] = translate_text(args[index])
        original(self, *args, **kwargs)
        for prop_name, source in sources.items():
            _remember_source(self, prop_name, source)

    try:
        QProgressDialog.__init__ = wrapped
    except Exception:
        _ORIGINALS.pop((QProgressDialog, '__init__', 'progress'), None)


def _patch_menu_add_action():
    original = QMenu.addAction
    _ORIGINALS[(QMenu, 'addAction')] = original

    def wrapped(self, *args, **kwargs):
        args = list(args)
        source = None
        for index, value in enumerate(args):
            if isinstance(value, str):
                source = value
                args[index] = translate_text(value)
                break
        action = original(self, *args, **kwargs)
        if source is not None and action is not None:
            _remember_source(action, 'text', source)
        return action

    try:
        QMenu.addAction = wrapped
    except Exception:
        _ORIGINALS.pop((QMenu, 'addAction'), None)


def _patch_messagebox_add_button():
    original = QMessageBox.addButton
    _ORIGINALS[(QMessageBox, 'addButton')] = original

    def wrapped(self, *args, **kwargs):
        args = list(args)
        source = None
        if args and isinstance(args[0], str):
            source = args[0]
            args[0] = translate_text(args[0])
        button = original(self, *args, **kwargs)
        if source is not None and button is not None:
            _remember_source(button, 'text', source)
        return button

    try:
        QMessageBox.addButton = wrapped
    except Exception:
        _ORIGINALS.pop((QMessageBox, 'addButton'), None)


def _patch_combo_box():
    original_add_item = QComboBox.addItem
    original_add_items = QComboBox.addItems
    _ORIGINALS[(QComboBox, 'addItem')] = original_add_item
    _ORIGINALS[(QComboBox, 'addItems')] = original_add_items

    def add_item(self, *args, **kwargs):
        args = list(args)
        for index, value in enumerate(args):
            if isinstance(value, str):
                args[index] = translate_text(value)
                break
        return original_add_item(self, *args, **kwargs)

    def add_items(self, texts):
        try:
            texts = [translate_text(t) if isinstance(t, str) else t for t in texts]
        except Exception:
            pass
        return original_add_items(self, texts)

    try:
        QComboBox.addItem = add_item
        QComboBox.addItems = add_items
    except Exception:
        _ORIGINALS.pop((QComboBox, 'addItem'), None)
        _ORIGINALS.pop((QComboBox, 'addItems'), None)


def _patch_static_dialogs():
    _patch_static_method(QMessageBox, 'information', [1, 2])
    _patch_static_method(QMessageBox, 'warning', [1, 2])
    _patch_static_method(QMessageBox, 'critical', [1, 2])
    _patch_static_method(QMessageBox, 'question', [1, 2])
    _patch_static_method(QInputDialog, 'getItem', [1, 2])
    _patch_static_method(QInputDialog, 'getText', [1, 2])
    _patch_static_method(QFileDialog, 'getOpenFileName', [1, 3])
    _patch_static_method(QFileDialog, 'getOpenFileNames', [1, 3])
    _patch_static_method(QFileDialog, 'getSaveFileName', [1, 3])
    _patch_static_method(QFileDialog, 'getExistingDirectory', [1])


def _patch_static_method(cls, method_name, text_indices):
    original = getattr(cls, method_name, None)
    if original is None:
        return
    _ORIGINALS[(cls, method_name)] = original

    def wrapped(*args, **kwargs):
        args = list(args)
        for index in text_indices:
            if len(args) > index and isinstance(args[index], str):
                args[index] = translate_text(args[index])
        for key in ('caption', 'title', 'text', 'label', 'filter'):
            if isinstance(kwargs.get(key), str):
                kwargs[key] = translate_text(kwargs[key])
        return original(*args, **kwargs)

    try:
        setattr(cls, method_name, wrapped)
    except Exception:
        _ORIGINALS.pop((cls, method_name), None)


def _patch_tray_message():
    original = QSystemTrayIcon.showMessage
    _ORIGINALS[(QSystemTrayIcon, 'showMessage')] = original

    def wrapped(self, title, message='', *args, **kwargs):
        return original(self, translate_text(title), translate_text(message), *args, **kwargs)

    try:
        QSystemTrayIcon.showMessage = wrapped
    except Exception:
        _ORIGINALS.pop((QSystemTrayIcon, 'showMessage'), None)


def _apply_to_object(obj):
    global _APPLYING_TEXT
    if obj is None:
        return
    _APPLYING_TEXT = True
    try:
        if isinstance(obj, QLabel):
            _apply_text_method(obj, QLabel, 'setText', 'text')
        if isinstance(obj, QPushButton):
            _apply_text_method(obj, QPushButton, 'setText', 'text')
        if isinstance(obj, QCheckBox):
            _apply_text_method(obj, QCheckBox, 'setText', 'text')
        if isinstance(obj, QGroupBox):
            _apply_text_method(obj, QGroupBox, 'setTitle', 'title')
        if isinstance(obj, QLineEdit):
            _apply_text_method(obj, QLineEdit, 'setPlaceholderText', 'placeholderText')
        if isinstance(obj, QTextEdit):
            _apply_text_method(obj, QTextEdit, 'setPlaceholderText', 'placeholderText')
        if isinstance(obj, QAction):
            _apply_text_method(obj, QAction, 'setText', 'text')
            _apply_text_method(obj, QAction, 'setToolTip', 'toolTip')
        if isinstance(obj, QWidget):
            _apply_text_method(obj, QWidget, 'setWindowTitle', 'windowTitle')
            _apply_text_method(obj, QWidget, 'setToolTip', 'toolTip')
        if isinstance(obj, QSystemTrayIcon):
            _apply_text_method(obj, QSystemTrayIcon, 'setToolTip', 'toolTip')
    finally:
        _APPLYING_TEXT = False


def _apply_text_method(obj, cls, method_name, prop_name):
    source = _read_source(obj, prop_name)
    if not isinstance(source, str) or not source:
        current = _current_text(obj, prop_name)
        if isinstance(current, str) and current in _TEXTS:
            source = current
            try:
                obj.setProperty(_source_prop(prop_name), source)
            except Exception:
                pass
        else:
            return
    text = translate_text(source)
    _call_original(cls, method_name, obj, text)


def _current_text(obj, prop_name):
    try:
        if prop_name == 'text' and hasattr(obj, 'text'):
            return obj.text()
        if prop_name == 'title' and hasattr(obj, 'title'):
            return obj.title()
        if prop_name == 'windowTitle' and hasattr(obj, 'windowTitle'):
            return obj.windowTitle()
        if prop_name == 'placeholderText' and hasattr(obj, 'placeholderText'):
            return obj.placeholderText()
        if prop_name == 'toolTip' and hasattr(obj, 'toolTip'):
            return obj.toolTip()
    except Exception:
        return None
    return None
