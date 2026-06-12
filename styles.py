"""苹果风格 QSS 样式表"""

COLORS = {
    'accent': '#2F7BFF',
    'accent_hover': '#1F6EF4',
    'accent_pressed': '#185ED4',
}

STYLE = """
* {
    font-family: "PingFang SC", "Microsoft YaHei UI", "Segoe UI", "SF Pro Display", sans-serif;
    outline: none;
}

QMainWindow, QWidget {
    background: #FBFBFD;
}

#sidebar {
    background: #F4F4F6;
    border-right: 1px solid #E6E6EA;
}

#right_panel {
    background: #FBFBFD;
}

#right_stack {
    background: #FBFBFD;
}

/* === 顶部主要按钮 === */
#new_button {
    background: @accent;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 9px 14px;
    font-size: 13px;
    font-weight: 600;
}

#new_button:hover {
    background: @accent_hover;
}

#new_button:pressed {
    background: @accent_pressed;
}

#more_button {
    background: rgba(255, 255, 255, 180);
    color: #65758B;
    border: 1px solid #DFDFE4;
    border-radius: 8px;
    font-size: 18px;
    font-weight: 700;
    padding: 0;
    padding-bottom: 6px;
}

#more_button:hover {
    background: #FFFFFF;
    color: #263548;
}

#more_button:pressed {
    background: #EBEBED;
}

/* === 搜索框 === */
#search_box {
    background: rgba(255, 255, 255, 210);
    border: 1px solid #E0E0E5;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #263548;
    selection-background-color: @accent;
    selection-color: #FFFFFF;
}

#search_box:focus {
    border: 1px solid @accent;
    background: #FFFFFF;
}

/* === 模式切换 (文字/截图) === */
#mode_btn_left, #mode_btn_right {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    color: #65758B;
    font-size: 12px;
    font-weight: 500;
    padding: 5px 14px;
}

#mode_btn_left {
    border-top-left-radius: 7px;
    border-bottom-left-radius: 7px;
    border-right: none;
}

#mode_btn_right {
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}

#mode_btn_left:hover, #mode_btn_right:hover {
    background: #F5F5F7;
}

#mode_btn_left:checked, #mode_btn_right:checked {
    background: @accent;
    border-color: @accent;
    color: white;
}

#mode_btn_left:checked {
    border-right: 1px solid @accent;
}

/* === 视图切换 (活跃/归档) === */
#view_btn_left, #view_btn_right {
    background: rgba(255, 255, 255, 170);
    border: 1px solid #E0E0E5;
    color: #65758B;
    font-size: 12px;
    font-weight: 500;
    padding: 7px 10px;
}

#view_btn_left {
    border-top-left-radius: 8px;
    border-bottom-left-radius: 8px;
    border-right: none;
}

#view_btn_right {
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}

#view_btn_left:hover, #view_btn_right:hover {
    background: #FFFFFF;
}

#view_btn_left:checked, #view_btn_right:checked {
    background: #263548;
    border-color: #263548;
    color: white;
}

#view_btn_left:checked {
    border-right: 1px solid #263548;
}

/* === 分类筛选 === */
#timeline_category_filter {
    background: rgba(255, 255, 255, 190);
    border: 1px solid #E0E0E5;
    border-radius: 8px;
    padding: 7px 12px;
    color: #263548;
    font-size: 12px;
    min-width: 132px;
}

#timeline_category_filter::drop-down {
    border: none;
    width: 22px;
}

#timeline_category_filter::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8B98AA;
    width: 0;
    height: 0;
    margin-right: 8px;
}

#timeline_category_filter:hover {
    border: 1px solid #C7C7CC;
    background: #FFFFFF;
}

#timeline_category_filter QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E5E5E7;
    border-radius: 8px;
    selection-background-color: @accent;
    selection-color: white;
    outline: none;
    padding: 4px;
}

/* === 列表 === */
#note_list {
    background: transparent;
    border: none;
    outline: none;
}

#note_list::item {
    border: none;
}

/* === 侧栏底部时间线按钮 === */
#timeline_btn {
    background: #FFFFFF;
    color: #263548;
    border: 1px solid #DFDFE4;
    border-radius: 8px;
    padding: 11px 12px;
    font-size: 13px;
    font-weight: 600;
    text-align: center;
}

#timeline_btn:hover {
    background: #F5F5F7;
    border: 1px solid #C7C7CC;
}

#timeline_btn:pressed {
    background: #EBEBED;
}

/* === 编辑器 === */
#title_input {
    background: transparent;
    border: none;
    font-size: 28px;
    font-weight: 700;
    color: #263548;
    padding: 0;
    selection-background-color: @accent;
    selection-color: #FFFFFF;
}

#title_input:focus {
    border: none;
}

#editor_time {
    color: #8B98AA;
    font-size: 12px;
    padding: 0;
}

#note_category_combo {
    background: #FFFFFF;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    color: #263548;
    font-size: 12px;
    min-width: 120px;
    padding: 5px 10px;
}

#note_category_combo:hover {
    border: 1px solid #C7C7CC;
}

#note_category_combo::drop-down {
    border: none;
    width: 20px;
}

#note_category_combo::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8B98AA;
    width: 0;
    height: 0;
    margin-right: 7px;
}

#note_category_combo QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E5E5E7;
    border-radius: 8px;
    selection-background-color: @accent;
    selection-color: #FFFFFF;
    outline: none;
    padding: 4px;
}

#divider {
    background: #E8EEF8;
    border: none;
    margin: 8px 0 10px 0;
}

#content_edit {
    background: transparent;
    border: none;
    font-size: 15px;
    color: #263548;
    selection-background-color: #B0D5FF;
    selection-color: #263548;
    padding: 0;
}

#format_btn {
    background: #FFFFFF;
    color: #263548;
    border: 1px solid #D2D2D7;
    border-radius: 7px;
    padding: 0;
    font-size: 12px;
    font-weight: 700;
}

#format_btn:hover {
    background: #F5F5F7;
    border: 1px solid #C7C7CC;
}

#format_btn:checked {
    background: #EAF2FF;
    color: @accent;
    border: 1px solid #B9D1FF;
}

/* === 空状态 === */
#empty_state {
    background: #FBFBFD;
}

#empty_panel {
    background: #FFFFFF;
    border: 1px solid #E5ECF7;
    border-radius: 8px;
}

#empty_icon {
    background: #F5F5F7;
    color: #65758B;
    border-radius: 23px;
    font-size: 24px;
    font-weight: 700;
    min-width: 46px;
    min-height: 46px;
    max-width: 46px;
    max-height: 46px;
}

#empty_title {
    color: #263548;
    font-size: 21px;
    font-weight: 700;
}

#empty_message {
    color: #65758B;
    font-size: 13px;
}

#empty_primary_btn {
    background: @accent;
    color: #FFFFFF;
    border: 1px solid @accent;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

#empty_primary_btn:hover {
    background: @accent_hover;
}

#empty_secondary_btn {
    background: #FFFFFF;
    color: #263548;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}

#empty_secondary_btn:hover {
    background: #F5F5F7;
}

/* === 底部附件栏 === */
#attachment_bar {
    background: #FAFAFA;
    border-top: 1px solid #E8EEF8;
}

#att_section_title {
    font-size: 11px;
    color: #65758B;
    font-weight: 600;
}

#att_hint {
    font-size: 11px;
    color: #9AA8BA;
}

#att_add_btn {
    background: @accent;
    color: white;
    border: none;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 600;
    padding: 0;
}

#att_add_btn:hover {
    background: @accent_hover;
}

#att_scroll {
    background: transparent;
    border: none;
}

#att_empty {
    color: #C7C7CC;
    font-size: 12px;
    padding: 12px;
}

#attachment_card {
    background: #FFFFFF;
    border: 1px solid #E8EEF8;
    border-radius: 10px;
}

#attachment_card:hover {
    background: #F5F5F7;
    border: 1px solid #D2D2D7;
}

#attachment_card[categorized="true"] {
    border: 1px solid #9CC9FF;
}

#att_name {
    font-size: 12px;
    font-weight: 500;
    color: #263548;
}

#att_size {
    font-size: 11px;
    color: #8B98AA;
}

#att_category_filter {
    background: #FFFFFF;
    border: 1px solid #D7E4F5;
    border-radius: 8px;
    padding: 3px 22px 3px 8px;
    color: #263548;
    font-size: 11px;
    font-weight: 600;
    min-width: 96px;
}

#att_category_filter:hover {
    border: 1px solid @accent;
}

#att_category_filter::drop-down {
    border: none;
    width: 18px;
}

#att_category_filter QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #D7E4F5;
    selection-background-color: @accent;
    selection-color: #FFFFFF;
}

#att_category_badge {
    background: #EAF3FF;
    border: 1px solid #BBD7FF;
    border-radius: 8px;
    color: @accent_hover;
    font-size: 11px;
    font-weight: 700;
    padding: 1px 5px;
}

#att_delete_btn {
    background: rgba(60, 60, 67, 42);
    color: #FFFFFF;
    border: none;
    border-radius: 11px;
    font-size: 16px;
    font-weight: 700;
    padding: 0;
    padding-bottom: 2px;
}

#att_delete_btn:hover {
    background: #FF3B30;
    color: #FFFFFF;
}

#att_delete_btn:pressed {
    background: #D70015;
}

/* === 截图网格 === */
#screenshot_grid {
    background: #FAFAFA;
    border: none;
}

#screenshot_grid_inner {
    background: #FAFAFA;
}

#grid_empty {
    color: #C7C7CC;
    font-size: 14px;
    padding: 80px 20px;
}

/* === 截图缩略图 === */
#screenshot_thumb {
    background: #FFFFFF;
    border: 1px solid #E8EEF8;
    border-radius: 12px;
}

#screenshot_thumb:hover {
    border: 1px solid #C7DCFF;
    background: #FAFCFF;
}

#screenshot_thumb[selected="true"] {
    border: 2px solid @accent;
    background: #F4F9FF;
}

#screenshot_thumb[archived="true"] {
    background: #F1F8F2;
    border: 1px solid #C8E6CC;
}

#screenshot_thumb[archived="true"][selected="true"] {
    border: 2px solid @accent;
    background: #EFF8F2;
}

#screenshot_thumb[archived="true"]:hover {
    background: #ECF6EE;
    border: 1px solid #A8D7AE;
}

#screenshot_thumb[archived="true"][selected="true"]:hover {
    border: 2px solid @accent;
}

#screenshot_thumb[archived="true"] #thumb_image {
    background: #E5F1E7;
}

#thumb_image {
    background: #F5F5F7;
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
}

#thumb_memo {
    background: transparent;
    border: none;
    color: #263548;
    font-size: 12px;
    padding: 8px 12px;
    selection-background-color: @accent;
    selection-color: #FFFFFF;
}

#thumb_memo:focus {
    background: #F5F5F7;
    border-bottom-left-radius: 11px;
    border-bottom-right-radius: 11px;
}

#thumb_add_attachment {
    background: rgba(47, 123, 255, 210);
    color: #FFFFFF;
    border: none;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 700;
    padding: 0;
}

#thumb_add_attachment:hover {
    background: @accent_hover;
}

#thumb_attachment_empty {
    color: #C7C7CC;
    font-size: 11px;
}

#thumb_attachment_chip {
    background: #F5F7FA;
    border: 1px solid #E1E5EC;
    border-radius: 6px;
}

#thumb_attachment_chip:hover {
    background: #EAF3FF;
    border: 1px solid #BBD7FF;
}

#thumb_attachment_chip[categorized="true"] {
    background: #EAF3FF;
    border: 1px solid #9CC9FF;
}

#thumb_attachment_name {
    color: #263548;
    font-size: 11px;
    font-weight: 600;
}

#thumb_attachment_more {
    background: #F2F2F7;
    color: #65758B;
    border-radius: 6px;
    padding: 6px 7px;
    font-size: 11px;
    font-weight: 600;
}

#screenshot_thumb[archived="true"] #thumb_memo {
    color: #4D5C50;
    font-weight: 500;
}

#thumb_check {
    background: rgba(0, 0, 0, 110);
    color: rgba(255, 255, 255, 220);
    border: none;
    border-radius: 14px;
    font-size: 15px;
    font-weight: 700;
    padding: 0;
    padding-bottom: 2px;
}

#thumb_check:hover {
    background: rgba(0, 0, 0, 180);
    color: white;
}

#thumb_check[done="true"] {
    background: #34C759;
    color: white;
}

#thumb_check[done="true"]:hover {
    background: #2BB04E;
}

/* === 滚动条 === */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 4px 2px 4px 0;
}

QScrollBar::handle:vertical {
    background: #C7C7CC;
    border-radius: 4px;
    min-height: 26px;
}

QScrollBar::handle:vertical:hover {
    background: #9AA8BA;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
    width: 0;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0 4px 2px 4px;
}

QScrollBar::handle:horizontal {
    background: #C7C7CC;
    border-radius: 4px;
    min-width: 26px;
}

QScrollBar::handle:horizontal:hover {
    background: #9AA8BA;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
    height: 0;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* === 菜单 === */
QMenu {
    background: #FFFFFF;
    border: 1px solid #E5E5E7;
    border-radius: 10px;
    padding: 6px;
    color: #263548;
    font-size: 13px;
}

QMenu::item {
    padding: 7px 28px 7px 18px;
    border-radius: 6px;
}

QMenu::item:selected {
    background: @accent;
    color: white;
}

QMenu::separator {
    height: 1px;
    background: #E8EEF8;
    margin: 4px 8px;
}

/* === 消息框 === */
QMessageBox {
    background: #FFFFFF;
    color: #263548;
}

QMessageBox QLabel {
    color: #263548;
    font-size: 13px;
}

QMessageBox QPushButton {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 7px;
    padding: 7px 16px;
    color: #263548;
    font-size: 13px;
    min-width: 64px;
}

QMessageBox QPushButton:hover {
    background: #F5F5F7;
}

QMessageBox QPushButton:default {
    background: @accent;
    border: 1px solid @accent;
    color: white;
}

QMessageBox QPushButton:default:hover {
    background: @accent_hover;
}

QToolTip {
    background: #263548;
    color: #FFFFFF;
    border: none;
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 12px;
}

/* === 图片查看器工具栏 === */
#viewer_toolbar_btn {
    background: rgba(255, 255, 255, 35);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
}

#viewer_toolbar_btn:hover {
    background: rgba(255, 255, 255, 70);
}

#viewer_info {
    color: #C7C7CC;
    font-size: 12px;
}

/* === 归档照片弹窗 === */
#archive_photo_dialog {
    background: #FFFFFF;
}

#archive_dialog_title {
    color: #263548;
    font-size: 22px;
    font-weight: 700;
}

#archive_dialog_subtitle, #archive_dialog_hint {
    color: #65758B;
    font-size: 12px;
}

#archive_dialog_thumb {
    background: #F5F5F7;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
}

#archive_dialog_filename {
    color: #263548;
    font-size: 13px;
    font-weight: 600;
}

#archive_dialog_label {
    color: #65758B;
    font-size: 12px;
    font-weight: 600;
    min-width: 34px;
}

#archive_dialog_category {
    background: #F7F7F9;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    color: #263548;
    font-size: 13px;
    padding: 7px 10px;
}

#archive_dialog_category:focus {
    background: #FFFFFF;
    border: 1px solid @accent;
}

#archive_dialog_category::drop-down {
    border: none;
    width: 24px;
}

#archive_dialog_category::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8B98AA;
    width: 0;
    height: 0;
    margin-right: 8px;
}

#archive_dialog_category QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E5E5E7;
    border-radius: 8px;
    selection-background-color: @accent;
    selection-color: white;
    outline: none;
    padding: 4px;
}

#archive_dialog_content {
    background: #F7F7F9;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    color: #263548;
    font-size: 13px;
    padding: 10px;
    selection-background-color: #B0D5FF;
    selection-color: #263548;
}

#archive_dialog_content:focus {
    background: #FFFFFF;
    border: 1px solid @accent;
}

#archive_dialog_cancel {
    background: #FFFFFF;
    color: #263548;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}

#archive_dialog_cancel:hover {
    background: #F5F5F7;
}

#archive_dialog_ok {
    background: @accent;
    color: #FFFFFF;
    border: 1px solid @accent;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

#archive_dialog_ok:hover {
    background: @accent_hover;
}

#archive_dialog_ok:disabled {
    background: #E5EBF5;
    border: 1px solid #E5EBF5;
    color: #8E8E93;
}

/* === 时间线 === */
#timeline_header_box {
    background: #FFFFFF;
    border-bottom: 1px solid #E5ECF7;
}

#timeline_header {
    color: #263548;
    font-size: 26px;
    font-weight: 700;
}

#timeline_subtitle {
    color: #8B98AA;
    font-size: 12px;
}

#timeline_filter_combo {
    background: #FFFFFF;
    border: 1px solid #E0E0E5;
    border-radius: 8px;
    color: #263548;
    font-size: 12px;
    min-width: 108px;
    padding: 7px 10px;
}

#timeline_filter_combo:hover {
    border: 1px solid #C7C7CC;
}

#timeline_filter_combo::drop-down {
    border: none;
    width: 20px;
}

#timeline_filter_combo::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8B98AA;
    width: 0;
    height: 0;
    margin-right: 7px;
}

#timeline_filter_combo QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E5E5E7;
    border-radius: 8px;
    selection-background-color: @accent;
    selection-color: #FFFFFF;
    outline: none;
    padding: 4px;
}

#timeline_filter_combo QLineEdit {
    background: transparent;
    border: none;
    color: #263548;
    padding: 0 2px;
    selection-background-color: @accent;
    selection-color: #FFFFFF;
}

#timeline_custom_range {
    background: transparent;
}

#timeline_date_label {
    color: #65758B;
    font-size: 12px;
    font-weight: 600;
}

#timeline_date_edit {
    background: #FFFFFF;
    border: 1px solid #E0E0E5;
    border-radius: 8px;
    color: #263548;
    font-size: 12px;
    min-width: 92px;
    padding: 7px 8px;
}

#timeline_date_edit:hover {
    border: 1px solid #C7C7CC;
}

#timeline_date_edit:focus {
    border: 1px solid @accent;
}

#timeline_date_edit::drop-down {
    border: none;
    width: 18px;
}

#timeline_date_edit::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8B98AA;
    width: 0;
    height: 0;
    margin-right: 6px;
}

#timeline_review_box {
    background: #FBFBFD;
    border-bottom: 1px solid #E5ECF7;
}

#timeline_stat_card {
    background: #FFFFFF;
    border: 1px solid #E5ECF7;
    border-radius: 8px;
}

#timeline_stat_value {
    color: #263548;
    font-size: 18px;
    font-weight: 700;
}

#timeline_stat_label {
    color: #8B98AA;
    font-size: 11px;
    font-weight: 600;
}

#timeline_detail_title {
    background: #FBFBFD;
    color: #65758B;
    font-size: 11px;
    font-weight: 700;
    padding: 12px 24px 6px 24px;
}

#timeline_list {
    background: #FBFBFD;
    border: none;
    outline: none;
}

#timeline_list::item {
    border: none;
}

#timeline_date {
    background: transparent;
    color: #65758B;
    font-size: 11px;
    font-weight: 700;
    padding: 16px 24px 6px 24px;
}

#timeline_item, #timeline_note_item {
    background: #FFFFFF;
    border: 1px solid #E5ECF7;
    border-radius: 10px;
    margin: 4px 20px;
}

#timeline_item:hover, #timeline_note_item:hover {
    background: #F7FAFF;
    border: 1px solid #C7DCFF;
}

#timeline_thumb {
    background: #F5F5F7;
    border-radius: 6px;
}

#timeline_memo {
    color: #263548;
    font-size: 14px;
    font-weight: 600;
}

#timeline_memo_empty {
    color: #C7C7CC;
    font-size: 13px;
    font-style: italic;
}

#timeline_meta {
    color: #8B98AA;
    font-size: 11px;
}

#timeline_time {
    color: #8B98AA;
    font-size: 12px;
    font-weight: 600;
}

#timeline_note_icon {
    background: #EAF7EE;
    color: #2DA44E;
    border-radius: 21px;
    font-size: 19px;
    font-weight: 800;
}

#timeline_note_title {
    color: #263548;
    font-size: 14px;
    font-weight: 700;
}

#timeline_note_preview {
    color: #65758B;
    font-size: 12px;
}

#timeline_empty {
    color: #C7C7CC;
    font-size: 13px;
    padding: 80px 20px;
}

#timeline_stat_sub {
    color: #8B98AA;
    font-size: 11px;
}

#timeline_streak_card {
    background: #FFFFFF;
    border: 1px solid #FFE2B8;
    border-left: 3px solid #FF9F0A;
    border-radius: 8px;
}

#timeline_streak_value {
    color: #FF9F0A;
    font-size: 18px;
    font-weight: 700;
}

#timeline_insight_strip {
    background: #FFFFFF;
    border: 1px solid #E5ECF7;
    border-radius: 10px;
}

#timeline_insight_label {
    color: #65758B;
    font-size: 12px;
}

#timeline_insight_sep {
    background: #ECF1F8;
    border: none;
}

#timeline_review_scroll, #timeline_review_scroll > QWidget {
    background: transparent;
    border: none;
}

#timeline_review_scroll QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 2px 1px 2px 0;
}

#timeline_review_scroll QScrollBar::handle:vertical {
    background: #D4DCE8;
    border-radius: 4px;
    min-height: 32px;
}

#timeline_review_scroll QScrollBar::handle:vertical:hover {
    background: #B9C4D4;
}

#timeline_review_scroll QScrollBar::add-line:vertical,
#timeline_review_scroll QScrollBar::sub-line:vertical {
    height: 0;
}

#timeline_review_scroll QScrollBar::add-page:vertical,
#timeline_review_scroll QScrollBar::sub-page:vertical {
    background: transparent;
}

/* === 最近删除 === */
#deleted_header_box {
    background: #FFFFFF;
    border-bottom: 1px solid #E5ECF7;
}

#deleted_header {
    color: #263548;
    font-size: 26px;
    font-weight: 700;
}

#deleted_subtitle {
    color: #8B98AA;
    font-size: 12px;
}

#deleted_list {
    background: #FBFBFD;
    border: none;
    outline: none;
    padding: 12px 14px;
}

#deleted_list::item {
    background: #FFFFFF;
    border: 1px solid #E5ECF7;
    border-radius: 8px;
    color: #263548;
    padding: 9px 14px;
    margin: 4px 0;
}

#deleted_list::item:selected {
    background: #E8F2FF;
    border: 1px solid #B7D6FF;
}

#deleted_empty {
    color: #C7C7CC;
    font-size: 13px;
    padding: 80px 20px;
}

#deleted_restore_btn {
    background: @accent;
    border: 1px solid @accent;
    border-radius: 8px;
    color: #FFFFFF;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

#deleted_restore_btn:hover {
    background: @accent_hover;
}

#deleted_restore_btn:disabled {
    background: #E5EBF5;
    border: 1px solid #E5EBF5;
    color: #8E8E93;
}

#deleted_delete_btn {
    background: #FFFFFF;
    border: 1px solid #FFB3AD;
    border-radius: 8px;
    color: #D70015;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

#deleted_delete_btn:hover {
    background: #FFF1F0;
}

#deleted_delete_btn:disabled {
    background: #FFFFFF;
    border: 1px solid #E5EBF5;
    color: #C7C7CC;
}

/* === 外观与文字配置 === */
#customization_dialog {
    background: #FBFBFD;
}

#customization_tabs::pane {
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    background: #FFFFFF;
}

#customization_tabs QTabBar::tab {
    background: transparent;
    color: #65758B;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

#customization_tabs QTabBar::tab:selected {
    color: @accent;
}

#customization_hint {
    color: #65758B;
    font-size: 12px;
}

#customization_text_table {
    background: #FFFFFF;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    gridline-color: #EFEFF4;
    selection-background-color: #E8F2FF;
    selection-color: #263548;
}

#customization_text_table QHeaderView::section {
    background: #F5F5F7;
    color: #65758B;
    border: none;
    border-bottom: 1px solid #E5EBF5;
    padding: 8px;
    font-size: 12px;
    font-weight: 700;
}

#customization_qss_editor {
    background: #1F2328;
    color: #F0F3F6;
    border: 1px solid #D8D8DE;
    border-radius: 8px;
    padding: 12px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
    selection-background-color: @accent;
}

/* === 账户入口 === */
#account_dialog {
    background: #FBFBFD;
}

#account_title {
    color: #263548;
    font-size: 30px;
    font-weight: 700;
}

#account_title_small {
    color: #263548;
    font-size: 22px;
    font-weight: 700;
}

#account_subtitle {
    color: #8B98AA;
    font-size: 12px;
}

#account_field {
    background: #FFFFFF;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    color: #263548;
    font-size: 14px;
    padding: 11px 13px;
    selection-background-color: @accent;
    selection-color: #FFFFFF;
}

#account_field:focus {
    border: 1px solid @accent;
}

#account_primary {
    background: @accent;
    border: 1px solid @accent;
    border-radius: 8px;
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 600;
    padding: 10px 14px;
}

#account_primary:hover {
    background: @accent_hover;
}

#account_secondary, #account_choice {
    background: #FFFFFF;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    color: #263548;
    font-size: 14px;
    font-weight: 500;
    padding: 10px 14px;
}

#account_secondary:hover, #account_choice:hover {
    background: #F5F5F7;
}

#account_danger {
    background: #FFFFFF;
    border: 1px solid #FFD5D2;
    border-radius: 8px;
    color: #D70015;
    font-size: 14px;
    font-weight: 500;
    padding: 10px 14px;
}

#account_danger:hover {
    background: #FFF2F1;
}

#account_flat {
    background: transparent;
    border: none;
    color: #65758B;
    font-size: 13px;
    padding: 8px 12px;
}

#account_flat:hover {
    color: #263548;
}

#account_error {
    color: #D70015;
    font-size: 12px;
}

#account_check {
    color: #263548;
    font-size: 13px;
    spacing: 8px;
}

#account_line {
    background: #E8EEF8;
    border: none;
    max-height: 1px;
}

/* === Reference-inspired main shell === */
#app_shell {
    background: #F6F9FF;
}

#sidebar {
    background: rgba(247, 250, 255, 226);
    border: 1px solid #E5ECF7;
    border-top-left-radius: 12px;
    border-bottom-left-radius: 12px;
    border-right: 1px solid #D9E3F3;
}

#right_panel, #right_stack, #empty_state {
    background: #FEFEFF;
    border-top-right-radius: 12px;
    border-bottom-right-radius: 12px;
}

#new_button {
    background: @accent;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    min-height: 38px;
    padding: 0 18px;
    font-size: 14px;
    font-weight: 600;
}

#new_button:hover {
    background: @accent_hover;
}

#new_button:pressed {
    background: @accent_pressed;
}

#more_button {
    background: rgba(255, 255, 255, 210);
    color: #8B98AA;
    border: 1px solid #E4EAF4;
    border-radius: 8px;
    font-size: 20px;
    font-weight: 700;
    padding: 0 0 7px 0;
}

#more_button:hover {
    background: #FFFFFF;
    color: #52627A;
}

#mode_btn_left, #mode_btn_right,
#view_btn_left, #view_btn_right {
    background: rgba(255, 255, 255, 190);
    border: 1px solid #E5EBF5;
    color: #65758B;
    font-size: 12px;
    font-weight: 600;
    min-height: 34px;
    padding: 0 10px;
}

#mode_btn_left, #view_btn_left {
    border-top-left-radius: 8px;
    border-bottom-left-radius: 8px;
    border-right: none;
}

#mode_btn_right, #view_btn_right {
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}

#mode_btn_left:checked, #mode_btn_right:checked,
#view_btn_left:checked, #view_btn_right:checked {
    background: #EAF2FF;
    border-color: #B9D1FF;
    color: @accent;
}

#mode_btn_left:checked, #view_btn_left:checked {
    border-right: 1px solid #B9D1FF;
}

#search_box {
    background: #FFFFFF;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    color: #27364A;
    min-height: 34px;
    padding: 0 12px;
    font-size: 12px;
}

#search_box:focus {
    background: #FFFFFF;
    border: 1px solid #B9D1FF;
}

#timeline_category_filter {
    background: #FFFFFF;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    color: #65758B;
    min-height: 34px;
    padding: 0 10px;
}

#note_list {
    background: transparent;
    border: none;
    outline: none;
}

#timeline_btn {
    background: #FFFFFF;
    color: #52627A;
    border: 1px solid #E5EBF5;
    border-radius: 8px;
    min-height: 38px;
    padding: 0 12px;
    font-size: 13px;
    font-weight: 600;
}

#timeline_btn:hover {
    background: #F7FBFF;
    border: 1px solid #D4E2F7;
    color: @accent;
}

#screenshot_grid, #screenshot_grid_inner {
    background: #FEFEFF;
}

#drop_hint_card, #empty_panel {
    background: rgba(255, 255, 255, 130);
    border: 1px dashed #BFDAFF;
    border-radius: 10px;
}

#drop_hint_icon, #empty_icon {
    background: #EAF2FF;
    color: @accent;
    border-radius: 22px;
    font-size: 24px;
    font-weight: 700;
    min-width: 44px;
    min-height: 44px;
    max-width: 44px;
    max-height: 44px;
}

#drop_hint_title, #empty_title {
    color: #52627A;
    font-size: 16px;
    font-weight: 700;
}

#drop_hint_subtitle, #empty_message {
    color: #9AA8BA;
    font-size: 13px;
}

#empty_primary_btn {
    background: @accent;
    border: 1px solid @accent;
    border-radius: 8px;
    min-height: 34px;
}

#empty_secondary_btn {
    border-radius: 8px;
    border: 1px solid #E5EBF5;
    color: #52627A;
    min-height: 34px;
}

#empty_secondary_btn:hover {
    background: #F7FBFF;
    border: 1px solid #D4E2F7;
}

#attachment_bar {
    background: #FAFCFF;
    border-top: 1px solid #E8EEF8;
}

#title_input {
    color: #263548;
}

#content_edit {
    color: #263548;
}
"""

for _k in sorted(COLORS, key=len, reverse=True):
    STYLE = STYLE.replace('@' + _k, COLORS[_k])
