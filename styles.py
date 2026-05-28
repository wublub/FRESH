"""苹果风格 QSS 样式表"""

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
    background: #007AFF;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 9px 14px;
    font-size: 13px;
    font-weight: 600;
}

#new_button:hover {
    background: #0A84FF;
}

#new_button:pressed {
    background: #0066D6;
}

#more_button {
    background: rgba(255, 255, 255, 180);
    color: #6E6E73;
    border: 1px solid #DFDFE4;
    border-radius: 8px;
    font-size: 18px;
    font-weight: 700;
    padding: 0;
    padding-bottom: 6px;
}

#more_button:hover {
    background: #FFFFFF;
    color: #1D1D1F;
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
    color: #1D1D1F;
    selection-background-color: #007AFF;
    selection-color: #FFFFFF;
}

#search_box:focus {
    border: 1px solid #007AFF;
    background: #FFFFFF;
}

/* === 模式切换 (文字/截图) === */
#mode_btn_left, #mode_btn_right {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    color: #6E6E73;
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
    background: #007AFF;
    border-color: #007AFF;
    color: white;
}

#mode_btn_left:checked {
    border-right: 1px solid #007AFF;
}

/* === 视图切换 (活跃/归档) === */
#view_btn_left, #view_btn_right {
    background: rgba(255, 255, 255, 170);
    border: 1px solid #E0E0E5;
    color: #6E6E73;
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
    background: #1D1D1F;
    border-color: #1D1D1F;
    color: white;
}

#view_btn_left:checked {
    border-right: 1px solid #1D1D1F;
}

/* === 分类筛选 === */
#timeline_category_filter {
    background: rgba(255, 255, 255, 190);
    border: 1px solid #E0E0E5;
    border-radius: 8px;
    padding: 7px 12px;
    color: #1D1D1F;
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
    border-top: 5px solid #86868B;
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
    selection-background-color: #007AFF;
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
    color: #1D1D1F;
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
    color: #1D1D1F;
    padding: 0;
    selection-background-color: #007AFF;
    selection-color: #FFFFFF;
}

#title_input:focus {
    border: none;
}

#editor_time {
    color: #86868B;
    font-size: 12px;
    padding: 0;
}

#note_category_combo {
    background: #FFFFFF;
    border: 1px solid #DADAE0;
    border-radius: 8px;
    color: #1D1D1F;
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
    border-top: 5px solid #86868B;
    width: 0;
    height: 0;
    margin-right: 7px;
}

#note_category_combo QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E5E5E7;
    border-radius: 8px;
    selection-background-color: #007AFF;
    selection-color: #FFFFFF;
    outline: none;
    padding: 4px;
}

#divider {
    background: #ECECEE;
    border: none;
    margin: 6px 0 10px 0;
}

#content_edit {
    background: transparent;
    border: none;
    font-size: 15px;
    color: #1D1D1F;
    selection-background-color: #B0D5FF;
    selection-color: #1D1D1F;
    padding: 0;
    line-height: 1.6;
}

#format_btn {
    background: #FFFFFF;
    color: #1D1D1F;
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
    background: #1D1D1F;
    color: #FFFFFF;
    border: 1px solid #1D1D1F;
}

/* === 空状态 === */
#empty_state {
    background: #FBFBFD;
}

#empty_panel {
    background: #FFFFFF;
    border: 1px solid #E8E8ED;
    border-radius: 8px;
}

#empty_icon {
    background: #F5F5F7;
    color: #6E6E73;
    border-radius: 23px;
    font-size: 24px;
    font-weight: 700;
    min-width: 46px;
    min-height: 46px;
    max-width: 46px;
    max-height: 46px;
}

#empty_title {
    color: #1D1D1F;
    font-size: 21px;
    font-weight: 700;
}

#empty_message {
    color: #6E6E73;
    font-size: 13px;
    line-height: 1.45;
}

#empty_primary_btn {
    background: #007AFF;
    color: #FFFFFF;
    border: 1px solid #007AFF;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

#empty_primary_btn:hover {
    background: #0A84FF;
}

#empty_secondary_btn {
    background: #FFFFFF;
    color: #1D1D1F;
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
    border-top: 1px solid #ECECEE;
}

#att_section_title {
    font-size: 11px;
    color: #6E6E73;
    font-weight: 600;
    letter-spacing: 1px;
}

#att_hint {
    font-size: 11px;
    color: #AEAEB2;
}

#att_add_btn {
    background: #007AFF;
    color: white;
    border: none;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 600;
    padding: 0;
}

#att_add_btn:hover {
    background: #0A84FF;
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
    border: 1px solid #ECECEE;
    border-radius: 10px;
}

#attachment_card:hover {
    background: #F5F5F7;
    border: 1px solid #D2D2D7;
}

#att_name {
    font-size: 12px;
    font-weight: 500;
    color: #1D1D1F;
}

#att_size {
    font-size: 10px;
    color: #86868B;
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
    border: 1px solid #ECECEE;
    border-radius: 12px;
}

#screenshot_thumb:hover {
    border: 1px solid #C7DCFF;
    background: #FAFCFF;
}

#screenshot_thumb[archived="true"] {
    background: #F1F8F2;
    border: 1px solid #C8E6CC;
}

#screenshot_thumb[archived="true"]:hover {
    background: #ECF6EE;
    border: 1px solid #A8D7AE;
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
    color: #1D1D1F;
    font-size: 12px;
    padding: 8px 12px;
    selection-background-color: #007AFF;
    selection-color: #FFFFFF;
}

#thumb_memo:focus {
    background: #F5F5F7;
    border-bottom-left-radius: 11px;
    border-bottom-right-radius: 11px;
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
    background: #AEAEB2;
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
    background: #AEAEB2;
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
    color: #1D1D1F;
    font-size: 13px;
}

QMenu::item {
    padding: 7px 28px 7px 18px;
    border-radius: 6px;
}

QMenu::item:selected {
    background: #007AFF;
    color: white;
}

QMenu::separator {
    height: 1px;
    background: #ECECEE;
    margin: 4px 8px;
}

/* === 消息框 === */
QMessageBox {
    background: #FFFFFF;
    color: #1D1D1F;
}

QMessageBox QLabel {
    color: #1D1D1F;
    font-size: 13px;
}

QMessageBox QPushButton {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 7px;
    padding: 7px 16px;
    color: #1D1D1F;
    font-size: 13px;
    min-width: 64px;
}

QMessageBox QPushButton:hover {
    background: #F5F5F7;
}

QMessageBox QPushButton:default {
    background: #007AFF;
    border: 1px solid #007AFF;
    color: white;
}

QMessageBox QPushButton:default:hover {
    background: #0A84FF;
}

QToolTip {
    background: #1D1D1F;
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
    color: #1D1D1F;
    font-size: 22px;
    font-weight: 700;
}

#archive_dialog_subtitle, #archive_dialog_hint {
    color: #6E6E73;
    font-size: 12px;
}

#archive_dialog_thumb {
    background: #F5F5F7;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
}

#archive_dialog_filename {
    color: #1D1D1F;
    font-size: 13px;
    font-weight: 600;
}

#archive_dialog_label {
    color: #6E6E73;
    font-size: 12px;
    font-weight: 600;
    min-width: 34px;
}

#archive_dialog_category {
    background: #F7F7F9;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    color: #1D1D1F;
    font-size: 13px;
    padding: 7px 10px;
}

#archive_dialog_category:focus {
    background: #FFFFFF;
    border: 1px solid #007AFF;
}

#archive_dialog_category::drop-down {
    border: none;
    width: 24px;
}

#archive_dialog_category::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #86868B;
    width: 0;
    height: 0;
    margin-right: 8px;
}

#archive_dialog_category QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E5E5E7;
    border-radius: 8px;
    selection-background-color: #007AFF;
    selection-color: white;
    outline: none;
    padding: 4px;
}

#archive_dialog_content {
    background: #F7F7F9;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    color: #1D1D1F;
    font-size: 13px;
    padding: 10px;
    selection-background-color: #B0D5FF;
    selection-color: #1D1D1F;
}

#archive_dialog_content:focus {
    background: #FFFFFF;
    border: 1px solid #007AFF;
}

#archive_dialog_cancel {
    background: #FFFFFF;
    color: #1D1D1F;
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
    background: #007AFF;
    color: #FFFFFF;
    border: 1px solid #007AFF;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

#archive_dialog_ok:hover {
    background: #0A84FF;
}

#archive_dialog_ok:disabled {
    background: #E5E5EA;
    border: 1px solid #E5E5EA;
    color: #8E8E93;
}

/* === 时间线 === */
#timeline_header_box {
    background: #FFFFFF;
    border-bottom: 1px solid #E8E8ED;
}

#timeline_header {
    color: #1D1D1F;
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.3px;
}

#timeline_subtitle {
    color: #86868B;
    font-size: 12px;
}

#timeline_filter_combo {
    background: #FFFFFF;
    border: 1px solid #E0E0E5;
    border-radius: 8px;
    color: #1D1D1F;
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
    border-top: 5px solid #86868B;
    width: 0;
    height: 0;
    margin-right: 7px;
}

#timeline_filter_combo QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E5E5E7;
    border-radius: 8px;
    selection-background-color: #007AFF;
    selection-color: #FFFFFF;
    outline: none;
    padding: 4px;
}

#timeline_review_box {
    background: #FBFBFD;
    border-bottom: 1px solid #E8E8ED;
}

#timeline_stat_card {
    background: #FFFFFF;
    border: 1px solid #E8E8ED;
    border-radius: 8px;
}

#timeline_stat_value {
    color: #1D1D1F;
    font-size: 18px;
    font-weight: 700;
}

#timeline_stat_label {
    color: #86868B;
    font-size: 11px;
    font-weight: 600;
}

#timeline_detail_title {
    background: #FBFBFD;
    color: #6E6E73;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
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
    color: #6E6E73;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
    padding: 16px 28px 6px 28px;
}

#timeline_item, #timeline_note_item {
    background: #FFFFFF;
    border: 1px solid #E8E8ED;
    border-radius: 8px;
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
    color: #1D1D1F;
    font-size: 14px;
    font-weight: 600;
}

#timeline_memo_empty {
    color: #C7C7CC;
    font-size: 13px;
    font-style: italic;
}

#timeline_meta {
    color: #86868B;
    font-size: 11px;
}

#timeline_time {
    color: #86868B;
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
    color: #1D1D1F;
    font-size: 14px;
    font-weight: 700;
}

#timeline_note_preview {
    color: #6E6E73;
    font-size: 12px;
}

#timeline_empty {
    color: #C7C7CC;
    font-size: 13px;
    padding: 80px 20px;
}

/* === 最近删除 === */
#deleted_header_box {
    background: #FFFFFF;
    border-bottom: 1px solid #E8E8ED;
}

#deleted_header {
    color: #1D1D1F;
    font-size: 26px;
    font-weight: 700;
}

#deleted_subtitle {
    color: #86868B;
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
    border: 1px solid #E8E8ED;
    border-radius: 8px;
    color: #1D1D1F;
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
    background: #007AFF;
    border: 1px solid #007AFF;
    border-radius: 8px;
    color: #FFFFFF;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

#deleted_restore_btn:hover {
    background: #0A84FF;
}

#deleted_restore_btn:disabled {
    background: #E5E5EA;
    border: 1px solid #E5E5EA;
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
    border: 1px solid #E5E5EA;
    color: #C7C7CC;
}

/* === 外观与文字配置 === */
#customization_dialog {
    background: #FBFBFD;
}

#customization_tabs::pane {
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    background: #FFFFFF;
}

#customization_tabs QTabBar::tab {
    background: transparent;
    color: #6E6E73;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

#customization_tabs QTabBar::tab:selected {
    color: #007AFF;
}

#customization_hint {
    color: #6E6E73;
    font-size: 12px;
}

#customization_text_table {
    background: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    gridline-color: #EFEFF4;
    selection-background-color: #E8F2FF;
    selection-color: #1D1D1F;
}

#customization_text_table QHeaderView::section {
    background: #F5F5F7;
    color: #6E6E73;
    border: none;
    border-bottom: 1px solid #E5E5EA;
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
    selection-background-color: #0969DA;
}

/* === 账户入口 === */
#account_dialog {
    background: #FBFBFD;
}

#account_title {
    color: #1D1D1F;
    font-size: 30px;
    font-weight: 700;
}

#account_title_small {
    color: #1D1D1F;
    font-size: 22px;
    font-weight: 700;
}

#account_subtitle {
    color: #86868B;
    font-size: 12px;
}

#account_field {
    background: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    color: #1D1D1F;
    font-size: 14px;
    padding: 11px 13px;
    selection-background-color: #007AFF;
    selection-color: #FFFFFF;
}

#account_field:focus {
    border: 1px solid #007AFF;
}

#account_primary {
    background: #007AFF;
    border: 1px solid #007AFF;
    border-radius: 8px;
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 600;
    padding: 10px 14px;
}

#account_primary:hover {
    background: #0A84FF;
}

#account_secondary, #account_choice {
    background: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    color: #1D1D1F;
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
    color: #6E6E73;
    font-size: 13px;
    padding: 8px 12px;
}

#account_flat:hover {
    color: #1D1D1F;
}

#account_error {
    color: #D70015;
    font-size: 12px;
}

#account_check {
    color: #1D1D1F;
    font-size: 13px;
    spacing: 8px;
}

#account_line {
    background: #ECECEE;
    border: none;
    max-height: 1px;
}
"""
