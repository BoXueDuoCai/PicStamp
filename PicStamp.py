import sys
import os
import io
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QLabel, QLineEdit, QComboBox, QSpinBox, QSlider, 
                            QFileDialog, QListWidget, QGroupBox, QRadioButton, QButtonGroup,
                            QCheckBox, QScrollArea, QFrame, QSplitter, QMessageBox, QColorDialog,
                            QDoubleSpinBox, QProgressBar, QStatusBar, QToolBar, QGridLayout,
                            QSizePolicy, QSpacerItem, QTabWidget, QTextEdit)
from PyQt6.QtCore import Qt, QSize, QPoint, QRect, pyqtSignal, QThread, QIODevice
from PyQt6.QtGui import QPixmap, QImage, QColor, QFont, QFontDatabase, QPainter, QPen, QTextCursor
from PIL import Image, ImageDraw, ImageFont, ImageQt
import math

APP_VERSION = "v1.1.0" 

# 更可靠的stderr过滤器
class StderrFilter:
    def __init__(self, original):
        self.original = original
        
    def write(self, message):
        try:
            msg_str = str(message)
            # 过滤掉MMKV和libpng日志
            if any(x in msg_str for x in ['MMKV', 'libpng', 'mmap', 'MemoryFile', 'engine_0', 'isDiskOfMMAPFileCorrupted']):
                return
            self.original.write(message)
        except:
            pass
            
    def flush(self):
        try:
            self.original.flush()
        except:
            pass

# 应用过滤器
sys.stderr = StderrFilter(sys.stderr)


class WatermarkWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_signal = pyqtSignal(int, int)
    
    def __init__(self, images, settings, parent=None):
        super().__init__(parent)
        self.images = images
        self.settings = settings
        self.is_running = True
        
    def run(self):
        success_count = 0
        fail_count = 0
        
        for i, img_path in enumerate(self.images):
            if not self.is_running:
                break
                
            try:
                self.progress.emit(i + 1, len(self.images), os.path.basename(img_path))
                
                img = Image.open(img_path)
                original_format = img.format if img.format else 'JPEG'
                original_info = img.info.copy()
                original_size = img.size
                
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                    
                watermarked = self.apply_watermark(img, self.settings)
                
                if watermarked.size != original_size:
                    watermarked = watermarked.resize(original_size, Image.Resampling.LANCZOS)
                
                output_format = self.settings.get('output_format', '原格式')
                if output_format == '原格式':
                    output_format = original_format
                
                if self.settings.get('output_mode') == "new":
                    base, ext = os.path.splitext(img_path)
                    ext_map = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 
                              'BMP': '.bmp', 'TIFF': '.tiff'}
                    new_ext = ext_map.get(output_format, '.jpg')
                    output_path = f"{base}_水印{new_ext}"
                    if '_水印' in base:
                        output_path = f"{base}{new_ext}"
                else:
                    output_path = img_path
                
                quality = self.settings.get('quality', 95)
                if output_format == 'JPEG':
                    if watermarked.mode == 'RGBA':
                        background = Image.new('RGB', watermarked.size, (255, 255, 255))
                        background.paste(watermarked, mask=watermarked.split()[-1])
                        watermarked = background
                    save_kwargs = {'quality': quality, 'optimize': True}
                    if 'exif' in original_info:
                        save_kwargs['exif'] = original_info['exif']
                    watermarked.save(output_path, 'JPEG', **save_kwargs)
                                   
                elif output_format == 'PNG':
                    save_kwargs = {'optimize': True, 'compress_level': 6}
                    if 'icc_profile' in original_info:
                        save_kwargs['icc_profile'] = original_info['icc_profile']
                    watermarked.save(output_path, 'PNG', **save_kwargs)
                                   
                elif output_format == 'WEBP':
                    watermarked.save(output_path, 'WEBP', quality=quality, method=6)
                    
                elif output_format == 'BMP':
                    if watermarked.mode == 'RGBA':
                        watermarked = watermarked.convert('RGB')
                    watermarked.save(output_path, 'BMP')
                    
                elif output_format == 'TIFF':
                    save_kwargs = {'compression': 'tiff_lzw'}
                    if 'icc_profile' in original_info:
                        save_kwargs['icc_profile'] = original_info['icc_profile']
                    watermarked.save(output_path, 'TIFF', **save_kwargs)
                else:
                    watermarked.save(output_path)
                    
                success_count += 1
                
            except Exception as e:
                fail_count += 1
                print(f"Error processing {img_path}: {str(e)}")
                import traceback
                traceback.print_exc()
        
        self.finished_signal.emit(success_count, fail_count)
    
    def apply_watermark(self, image, settings):
        img = image.copy()
        width, height = img.size
        
        mode = settings.get('position_mode', 'preset')
        opacity = settings.get('opacity', 128)
        rotation = settings.get('rotation', 0)
        margin_x = settings.get('margin_x', 20)
        margin_y = settings.get('margin_y', 20)
        
        if settings.get('watermark_type') == 'text':
            text = settings.get('text', '')
            if not text:
                return img
            
            font_size = settings.get('font_size', 50)
            font_family = settings.get('font_family', 'SimSun')
            
            font_obj = self.get_font(font_family, font_size, text)
            
            overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(overlay)
            
            bbox = draw.textbbox((0, 0), text, font=font_obj)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            color = settings.get('color', '#FFFFFF')
            rgb = self.parse_color(color)
            rgba = rgb + (opacity,)
            
            positions = self.calculate_positions(width, height, text_width, text_height,
                                               margin_x, margin_y, mode, settings)
            
            for x, y in positions:
                if rotation != 0:
                    txt_layer = Image.new('RGBA', (text_width + 20, text_height + 20), (255, 255, 255, 0))
                    txt_draw = ImageDraw.Draw(txt_layer)
                    txt_draw.text((10, 10), text, font=font_obj, fill=rgba)
                    rotated = txt_layer.rotate(-rotation, expand=True)
                    overlay.paste(rotated, (int(x - rotated.width/2 + text_width/2),
                                          int(y - rotated.height/2 + text_height/2)), rotated)
                else:
                    draw.text((x, y), text, font=font_obj, fill=rgba)
            
            img = Image.alpha_composite(img, overlay)
            
        else:
            wm_path = settings.get('watermark_image_path')
            if not wm_path or not os.path.exists(wm_path):
                return img
            
            wm = Image.open(wm_path).convert("RGBA")
            scale = settings.get('image_scale', 0.2)
            
            new_size = (int(wm.width * scale), int(wm.height * scale))
            if new_size[0] > 0 and new_size[1] > 0:
                wm = wm.resize(new_size, Image.Resampling.LANCZOS)
                
                alpha = wm.split()[-1]
                alpha = alpha.point(lambda p: int(p * opacity / 255))
                wm.putalpha(alpha)
                
                wm_width, wm_height = wm.size
                positions = self.calculate_positions(width, height, wm_width, wm_height,
                                                   margin_x, margin_y, mode, settings)
                
                overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
                for x, y in positions:
                    if rotation != 0:
                        rotated_wm = wm.rotate(-rotation, expand=True)
                        overlay.paste(rotated_wm, (int(x), int(y)), rotated_wm)
                    else:
                        overlay.paste(wm, (int(x), int(y)), wm)
                
                img = Image.alpha_composite(img, overlay)
        
        return img
    
    def get_font(self, font_family, font_size, text):
        chinese_fonts = [
            'SimSun', 'simsun', '宋体',
            'Microsoft YaHei', 'microsoft yahei', '微软雅黑',
            'SimHei', 'simhei', '黑体',
            'NSimSun', 'nsimsun', '新宋体',
            'FangSong', 'fangsong', '仿宋',
            'KaiTi', 'kaiti', '楷体',
            'LiSu', 'lisu', '隶书',
            'YouYuan', 'youyuan', '幼圆',
            'STSong', 'STHeiti', 'STKaiti', 'STFangsong',
            'Adobe Song Std', 'Adobe Heiti Std',
            'Source Han Sans SC', 'Source Han Serif SC',
            'Noto Sans CJK SC', 'Noto Serif CJK SC',
            'WenQuanYi Micro Hei', 'WenQuanYi Zen Hei'
        ]
        
        has_chinese = any(ord(char) > 127 for char in text)
        is_chinese_font = any(cf.lower() in font_family.lower() for cf in chinese_fonts)
        
        if has_chinese or is_chinese_font:
            if is_chinese_font:
                try:
                    return ImageFont.truetype(font_family, font_size)
                except:
                    pass
            
            for font_name in chinese_fonts:
                try:
                    return ImageFont.truetype(font_name, font_size)
                except:
                    continue
        
        try:
            return ImageFont.truetype(font_family, font_size)
        except:
            pass
        
        fallback_fonts = ['Arial', 'Times New Roman', 'Helvetica', 'Verdana']
        for font_name in fallback_fonts:
            try:
                return ImageFont.truetype(font_name, font_size)
            except:
                continue
        
        return ImageFont.load_default()
    
    def parse_color(self, color_str):
        try:
            if color_str.startswith('#') and len(color_str) == 7:
                return tuple(int(color_str[i:i+2], 16) for i in (1, 3, 5))
            elif color_str.startswith('#') and len(color_str) == 4:
                return tuple(int(color_str[i]*2, 16) for i in range(1, 4))
            elif color_str.lower() == 'white':
                return (255, 255, 255)
            elif color_str.lower() == 'black':
                return (0, 0, 0)
            elif color_str.lower() == 'red':
                return (255, 0, 0)
            elif color_str.lower() == 'green':
                return (0, 255, 0)
            elif color_str.lower() == 'blue':
                return (0, 0, 255)
            else:
                qcolor = QColor(color_str)
                if qcolor.isValid():
                    return (qcolor.red(), qcolor.green(), qcolor.blue())
                return (255, 255, 255)
        except:
            return (255, 255, 255)
    
    def calculate_positions(self, img_w, img_h, wm_w, wm_h, margin_x, margin_y, mode, settings):
        positions = []
        
        if mode == "full":
            spacing_x = settings.get('spacing_x', 200)
            spacing_y = settings.get('spacing_y', 150)
            
            for y in range(0, img_h, spacing_y):
                for x in range(0, img_w, spacing_x):
                    positions.append((x, y))
        
        elif mode == "custom":
            positions.append((img_w//2 - wm_w//2, img_h//2 - wm_h//2))
        
        else:
            preset_defs = {
                'top_left': (margin_x, margin_y),
                'top_center': (img_w//2 - wm_w//2, margin_y),
                'top_right': (img_w - wm_w - margin_x, margin_y),
                'center_left': (margin_x, img_h//2 - wm_h//2),
                'center': (img_w//2 - wm_w//2, img_h//2 - wm_h//2),
                'center_right': (img_w - wm_w - margin_x, img_h//2 - wm_h//2),
                'bottom_left': (margin_x, img_h - wm_h - margin_y),
                'bottom_center': (img_w//2 - wm_w//2, img_h - wm_h - margin_y),
                'bottom_right': (img_w - wm_w - margin_x, img_h - wm_h - margin_y)
            }
            
            selected_positions = settings.get('positions', ['bottom_right'])
            for pos_key in selected_positions:
                if pos_key in preset_defs:
                    positions.append(preset_defs[pos_key])
        
        return positions if positions else [(img_w//2 - wm_w//2, img_h//2 - wm_h//2)]
    
    def stop(self):
        self.is_running = False


class ImageLabel(QLabel):
    position_changed = pyqtSignal(int, int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #2C3E50;")
        self.setMinimumSize(400, 300)
        self.dragging = False
        self.drag_start = QPoint()
        self.watermark_pos = None
        self.preview_scale = 1.0
        
    def set_watermark_position(self, x, y):
        self.watermark_pos = QPoint(int(x), int(y))
        self.update()
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.watermark_pos:
            pos = event.pos()
            wm_rect = QRect(self.watermark_pos.x() - 50, self.watermark_pos.y() - 25, 100, 50)
            if wm_rect.contains(pos):
                self.dragging = True
                self.drag_start = pos
                
    def mouseMoveEvent(self, event):
        if self.dragging:
            delta = event.pos() - self.drag_start
            self.watermark_pos += delta
            self.drag_start = event.pos()
            self.update()
            if self.pixmap():
                img_x = int((self.watermark_pos.x() - (self.width() - self.pixmap().width()) // 2) / self.preview_scale)
                img_y = int((self.watermark_pos.y() - (self.height() - self.pixmap().height()) // 2) / self.preview_scale)
                self.position_changed.emit(img_x, img_y)
                
    def mouseReleaseEvent(self, event):
        self.dragging = False
        
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.watermark_pos and self.pixmap():
            painter = QPainter(self)
            pen = QPen(QColor(255, 0, 0))
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(self.watermark_pos.x() - 50, self.watermark_pos.y() - 25, 100, 50)
            painter.drawText(self.watermark_pos.x() - 20, self.watermark_pos.y() + 5, "水印")


class WatermarkApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PicStamp - 批量水印工具 - {APP_VERSION}")
        self.setGeometry(100, 100, 1200, 800)
        self.setMinimumSize(900, 600)
        
        self.images = []
        self.current_index = 0
        self.watermark_image_path = None
        self.custom_positions = {}
        self.preview_scale = 1.0
        self.current_color = "#FFFFFF"
        
        self.setup_ui()
        self.load_fonts()
        
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(10)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMaximumWidth(450)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(10)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.create_file_section(left_layout)
        self.create_type_section(left_layout)
        self.create_text_section(left_layout)
        self.create_image_section(left_layout)
        self.create_position_section(left_layout)
        self.create_advanced_section(left_layout)
        self.create_output_section(left_layout)
        
        left_scroll.setWidget(left_widget)
        splitter.addWidget(left_scroll)
        
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        toolbar = QHBoxLayout()
        self.prev_btn = QPushButton("◀ 上一张")
        self.next_btn = QPushButton("下一张 ▶")
        self.preview_label = QLabel("预览: 0/0")
        self.fit_btn = QPushButton("适应窗口")
        self.reset_pos_btn = QPushButton("重置位置")
        
        self.prev_btn.clicked.connect(self.prev_image)
        self.next_btn.clicked.connect(self.next_image)
        self.fit_btn.clicked.connect(self.fit_to_window)
        self.reset_pos_btn.clicked.connect(self.reset_positions)
        
        toolbar.addWidget(self.prev_btn)
        toolbar.addWidget(self.next_btn)
        toolbar.addWidget(self.preview_label)
        toolbar.addStretch()
        toolbar.addWidget(self.fit_btn)
        toolbar.addWidget(self.reset_pos_btn)
        
        right_layout.addLayout(toolbar)
        
        self.image_label = ImageLabel()
        self.image_label.position_changed.connect(self.on_position_changed)
        right_layout.addWidget(self.image_label, stretch=1)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)
        
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 800])
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
    def create_file_section(self, layout):
        group = QGroupBox("📁 图片选择")
        group_layout = QVBoxLayout(group)
        
        btn_layout = QHBoxLayout()
        add_file_btn = QPushButton("添加图片")
        add_folder_btn = QPushButton("添加文件夹")
        clear_btn = QPushButton("清空")
        
        add_file_btn.clicked.connect(self.add_images)
        add_folder_btn.clicked.connect(self.add_folder)
        clear_btn.clicked.connect(self.clear_images)
        
        btn_layout.addWidget(add_file_btn)
        btn_layout.addWidget(add_folder_btn)
        btn_layout.addWidget(clear_btn)
        group_layout.addLayout(btn_layout)
        
        self.file_list = QListWidget()
        self.file_list.currentRowChanged.connect(self.on_file_selected)
        group_layout.addWidget(self.file_list)
        
        self.file_count_label = QLabel("已选择: 0 张图片")
        group_layout.addWidget(self.file_count_label)
        
        layout.addWidget(group)
        
    def create_type_section(self, layout):
        group = QGroupBox("🔤 水印类型")
        group_layout = QHBoxLayout(group)
        
        self.type_group = QButtonGroup(self)
        self.text_radio = QRadioButton("文字水印")
        self.image_radio = QRadioButton("图片水印")
        self.text_radio.setChecked(True)
        
        self.type_group.addButton(self.text_radio, 0)
        self.type_group.addButton(self.image_radio, 1)
        self.type_group.buttonClicked.connect(self.on_type_changed)
        
        group_layout.addWidget(self.text_radio)
        group_layout.addWidget(self.image_radio)
        
        layout.addWidget(group)
        
    def create_text_section(self, layout):
        self.text_group = QGroupBox("✏️ 文字设置")
        group_layout = QVBoxLayout(self.text_group)
        
        group_layout.addWidget(QLabel("水印文字:"))
        self.text_edit = QLineEdit("样本文本")
        self.text_edit.textChanged.connect(self.update_preview)
        group_layout.addWidget(self.text_edit)
        
        font_layout = QHBoxLayout()
        
        font_layout.addWidget(QLabel("字体:"))
        self.font_combo = QComboBox()
        self.font_combo.currentTextChanged.connect(self.update_preview)
        font_layout.addWidget(self.font_combo)
        
        font_layout.addWidget(QLabel("字号:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 99999)
        self.size_spin.setValue(50)
        self.size_spin.valueChanged.connect(self.update_preview)
        font_layout.addWidget(self.size_spin)
        
        group_layout.addLayout(font_layout)
        
        color_layout = QHBoxLayout()
        
        color_layout.addWidget(QLabel("颜色:"))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(30, 25)
        self.color_btn.setStyleSheet("background-color: #FFFFFF;")
        self.color_btn.clicked.connect(self.choose_color)
        color_layout.addWidget(self.color_btn)
        
        color_layout.addWidget(QLabel("透明度:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 255)
        self.opacity_slider.setValue(128)
        self.opacity_slider.valueChanged.connect(self.update_preview)
        color_layout.addWidget(self.opacity_slider)
        
        self.opacity_label = QLabel("128")
        color_layout.addWidget(self.opacity_label)
        self.opacity_slider.valueChanged.connect(lambda v: self.opacity_label.setText(str(v)))
        
        group_layout.addLayout(color_layout)
        
        hint = QLabel("💡 提示：自动检测并使用中文字体")
        hint.setStyleSheet("color: gray; font-size: 10px;")
        group_layout.addWidget(hint)
        
        layout.addWidget(self.text_group)
        
    def create_image_section(self, layout):
        self.image_group = QGroupBox("🖼️ 图片水印设置")
        group_layout = QVBoxLayout(self.image_group)
        
        btn_layout = QHBoxLayout()
        select_img_btn = QPushButton("选择水印图片")
        select_img_btn.clicked.connect(self.choose_watermark_image)
        btn_layout.addWidget(select_img_btn)
        
        self.wm_img_label = QLabel("未选择")
        btn_layout.addWidget(self.wm_img_label)
        btn_layout.addStretch()
        
        group_layout.addLayout(btn_layout)
        
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("缩放比例:"))
        self.img_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.img_scale_slider.setRange(5, 100)
        self.img_scale_slider.setValue(20)
        self.img_scale_slider.valueChanged.connect(self.update_preview)
        scale_layout.addWidget(self.img_scale_slider)
        
        self.img_scale_label = QLabel("20%")
        scale_layout.addWidget(self.img_scale_label)
        self.img_scale_slider.valueChanged.connect(lambda v: self.img_scale_label.setText(f"{v}%"))
        
        group_layout.addLayout(scale_layout)
        
        layout.addWidget(self.image_group)
        self.image_group.setVisible(False)
        
    def create_position_section(self, layout):
        group = QGroupBox("📍 位置设置")
        group_layout = QVBoxLayout(group)
        
        mode_layout = QHBoxLayout()
        self.pos_mode_group = QButtonGroup(self)
        
        self.preset_radio = QRadioButton("预设位置")
        self.full_radio = QRadioButton("全页平铺")
        self.custom_radio = QRadioButton("自定义拖动")
        self.preset_radio.setChecked(True)
        
        self.pos_mode_group.addButton(self.preset_radio, 0)
        self.pos_mode_group.addButton(self.full_radio, 1)
        self.pos_mode_group.addButton(self.custom_radio, 2)
        self.pos_mode_group.buttonClicked.connect(self.on_position_mode_changed)
        
        mode_layout.addWidget(self.preset_radio)
        mode_layout.addWidget(self.full_radio)
        mode_layout.addWidget(self.custom_radio)
        group_layout.addLayout(mode_layout)
        
        self.preset_widget = QWidget()
        preset_layout = QGridLayout(self.preset_widget)
        
        positions = [
            ['top_left', 'top_center', 'top_right'],
            ['center_left', 'center', 'center_right'],
            ['bottom_left', 'bottom_center', 'bottom_right']
        ]
        names = {
            'top_left': '左上', 'top_center': '上中', 'top_right': '右上',
            'center_left': '左中', 'center': '中心', 'center_right': '右中',
            'bottom_left': '左下', 'bottom_center': '下中', 'bottom_right': '右下'
        }
        
        self.position_checks = {}
        for row, pos_row in enumerate(positions):
            for col, pos_key in enumerate(pos_row):
                chk = QCheckBox(names[pos_key])
                if pos_key == 'bottom_right':
                    chk.setChecked(True)
                chk.stateChanged.connect(self.update_preview)
                preset_layout.addWidget(chk, row, col)
                self.position_checks[pos_key] = chk
        
        group_layout.addWidget(self.preset_widget)
        
        self.full_widget = QWidget()
        full_layout = QHBoxLayout(self.full_widget)
        
        full_layout.addWidget(QLabel("间距 X:"))
        self.spacing_x_spin = QSpinBox()
        self.spacing_x_spin.setRange(10, 2000)
        self.spacing_x_spin.setValue(200)
        self.spacing_x_spin.valueChanged.connect(self.update_preview)
        full_layout.addWidget(self.spacing_x_spin)
        
        full_layout.addWidget(QLabel("Y:"))
        self.spacing_y_spin = QSpinBox()
        self.spacing_y_spin.setRange(10, 2000)
        self.spacing_y_spin.setValue(150)
        self.spacing_y_spin.valueChanged.connect(self.update_preview)
        full_layout.addWidget(self.spacing_y_spin)
        
        group_layout.addWidget(self.full_widget)
        self.full_widget.setVisible(False)
        
        self.custom_hint = QLabel("💡 在右侧预览图中拖动红色框调整位置")
        self.custom_hint.setStyleSheet("color: blue;")
        group_layout.addWidget(self.custom_hint)
        self.custom_hint.setVisible(False)
        
        layout.addWidget(group)
        
    def create_advanced_section(self, layout):
        group = QGroupBox("⚙️ 高级设置")
        group_layout = QVBoxLayout(group)
        
        rot_layout = QHBoxLayout()
        rot_layout.addWidget(QLabel("旋转:"))
        
        self.rot_slider = QSlider(Qt.Orientation.Horizontal)
        self.rot_slider.setRange(-180, 180)
        self.rot_slider.setValue(0)
        self.rot_slider.valueChanged.connect(self.on_rotation_changed)
        rot_layout.addWidget(self.rot_slider)
        
        self.rot_spin = QSpinBox()
        self.rot_spin.setRange(-180, 180)
        self.rot_spin.setValue(0)
        self.rot_spin.valueChanged.connect(self.on_rotation_spin_changed)
        rot_layout.addWidget(self.rot_spin)
        
        rot_layout.addWidget(QLabel("°"))
        
        rot_reset = QPushButton("重置")
        rot_reset.setFixedWidth(50)
        rot_reset.clicked.connect(lambda: self.rot_spin.setValue(0))
        rot_layout.addWidget(rot_reset)
        
        group_layout.addLayout(rot_layout)
        
        margin_layout = QHBoxLayout()
        
        margin_layout.addWidget(QLabel("水平边距:"))
        self.margin_x_spin = QSpinBox()
        self.margin_x_spin.setRange(0, 9999)
        self.margin_x_spin.setValue(20)
        self.margin_x_spin.valueChanged.connect(self.update_preview)
        margin_layout.addWidget(self.margin_x_spin)
        
        margin_layout.addWidget(QLabel("垂直边距:"))
        self.margin_y_spin = QSpinBox()
        self.margin_y_spin.setRange(0, 9999)
        self.margin_y_spin.setValue(20)
        self.margin_y_spin.valueChanged.connect(self.update_preview)
        margin_layout.addWidget(self.margin_y_spin)
        
        group_layout.addLayout(margin_layout)
        
        layout.addWidget(group)
        
    def create_output_section(self, layout):
        group = QGroupBox("💾 输出设置")
        group_layout = QVBoxLayout(group)
        
        self.output_new_radio = QRadioButton("保存为新文件")
        self.output_over_radio = QRadioButton("覆盖原文件 (谨慎!)")
        self.output_new_radio.setChecked(True)
        
        group_layout.addWidget(self.output_new_radio)
        group_layout.addWidget(self.output_over_radio)
        
        format_layout = QHBoxLayout()
        
        format_layout.addWidget(QLabel("格式:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(['原格式', 'JPEG', 'PNG', 'WEBP', 'BMP', 'TIFF'])
        self.format_combo.currentTextChanged.connect(self.update_preview)
        format_layout.addWidget(self.format_combo)
        
        format_layout.addWidget(QLabel("质量:"))
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(95)
        self.quality_slider.valueChanged.connect(self.on_quality_changed)
        format_layout.addWidget(self.quality_slider)
        
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(95)
        self.quality_spin.valueChanged.connect(self.on_quality_spin_changed)
        format_layout.addWidget(self.quality_spin)
        
        format_layout.addWidget(QLabel("%"))
        
        quality_reset = QPushButton("重置")
        quality_reset.setFixedWidth(50)
        quality_reset.clicked.connect(lambda: self.quality_spin.setValue(95))
        format_layout.addWidget(quality_reset)
        
        group_layout.addLayout(format_layout)
        
        hint = QLabel("✓ 无损处理：保持原图分辨率，仅叠加水印层")
        hint.setStyleSheet("color: green; font-size: 11px;")
        group_layout.addWidget(hint)
        
        self.start_btn = QPushButton("🚀 开始批量处理")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498DB;
                color: white;
                font-weight: bold;
                padding: 10px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
        """)
        self.start_btn.clicked.connect(self.start_processing)
        group_layout.addWidget(self.start_btn)
        
        layout.addWidget(group)
        
    def load_fonts(self):
        chinese_fonts = ['SimSun', 'Microsoft YaHei', 'SimHei', 'NSimSun', 
                        'FangSong', 'KaiTi', 'LiSu', 'YouYuan']
        english_fonts = ['Times New Roman', 'Arial', 'Helvetica', 'Courier New', 
                        'Verdana', 'Georgia']
        
        try:
            db = QFontDatabase()
            system_fonts = db.families()
            all_fonts = list(dict.fromkeys(chinese_fonts + english_fonts + system_fonts))
            self.font_combo.addItems(all_fonts[:60])
        except:
            self.font_combo.addItems(chinese_fonts + english_fonts)
        
        self.font_combo.setCurrentText('SimSun')
        
    def on_rotation_changed(self, value):
        self.rot_spin.blockSignals(True)
        self.rot_spin.setValue(value)
        self.rot_spin.blockSignals(False)
        self.update_preview()
        
    def on_rotation_spin_changed(self, value):
        self.rot_slider.blockSignals(True)
        self.rot_slider.setValue(value)
        self.rot_slider.blockSignals(False)
        self.update_preview()
        
    def on_quality_changed(self, value):
        self.quality_spin.blockSignals(True)
        self.quality_spin.setValue(value)
        self.quality_spin.blockSignals(False)
        
    def on_quality_spin_changed(self, value):
        self.quality_slider.blockSignals(True)
        self.quality_slider.setValue(value)
        self.quality_slider.blockSignals(False)
        
    def on_type_changed(self):
        is_text = self.text_radio.isChecked()
        self.text_group.setVisible(is_text)
        self.image_group.setVisible(not is_text)
        self.update_preview()
        
    def on_position_mode_changed(self):
        mode = 'preset'
        if self.full_radio.isChecked():
            mode = 'full'
        elif self.custom_radio.isChecked():
            mode = 'custom'
            
        self.preset_widget.setVisible(mode == 'preset')
        self.full_widget.setVisible(mode == 'full')
        self.custom_hint.setVisible(mode == 'custom')
        
        if mode == 'custom' and self.image_label.pixmap():
            self.image_label.watermark_pos = QPoint(self.image_label.width()//2, self.image_label.height()//2)
        else:
            self.image_label.watermark_pos = None
            
        self.update_preview()
        
    def on_position_changed(self, x, y):
        self.custom_positions[self.current_index] = (x, y)
        self.status_bar.showMessage(f"位置已保存: ({x}, {y})")
        
    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.current_color), self)
        if color.isValid():
            self.current_color = color.name()
            self.color_btn.setStyleSheet(f"background-color: {self.current_color};")
            self.update_preview()
            
    def choose_watermark_image(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "选择水印图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file:
            self.watermark_image_path = file
            self.wm_img_label.setText(os.path.basename(file)[:15])
            self.update_preview()
            
    def add_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp *.tiff *.webp *.gif)"
        )
        for f in files:
            if f not in self.images:
                self.images.append(f)
                self.file_list.addItem(os.path.basename(f))
        self.update_file_count()
        if files and self.current_index == 0:
            self.load_image(0)
            
    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            count = 0
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp', '.gif')):
                        path = os.path.join(root, file)
                        if path not in self.images:
                            self.images.append(path)
                            self.file_list.addItem(os.path.basename(path))
                            count += 1
            self.update_file_count()
            if count > 0 and self.current_index == 0:
                self.load_image(0)
                
    def clear_images(self):
        self.images = []
        self.file_list.clear()
        self.current_index = 0
        self.update_file_count()
        self.image_label.clear()
        self.image_label.setText("请先添加图片")
        
    def update_file_count(self):
        count = len(self.images)
        self.file_count_label.setText(f"已选择: {count} 张图片")
        self.preview_label.setText(f"预览: {self.current_index + 1}/{count}" if count > 0 else "预览: 0/0")
        
    def on_file_selected(self, index):
        if index >= 0:
            self.current_index = index
            self.load_image(index)
            
    def prev_image(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.file_list.setCurrentRow(self.current_index)
            self.load_image(self.current_index)
            
    def next_image(self):
        if self.current_index < len(self.images) - 1:
            self.current_index += 1
            self.file_list.setCurrentRow(self.current_index)
            self.load_image(self.current_index)
            
    def fit_to_window(self):
        self.update_preview()
        
    def reset_positions(self):
        self.custom_positions = {}
        self.status_bar.showMessage("已重置所有自定义位置")
        self.update_preview()
        
    def load_image(self, index):
        if not self.images or index >= len(self.images):
            return
        self.update_preview()
        
    def get_font(self, font_family, font_size, text):
        chinese_fonts = [
            'SimSun', 'simsun', '宋体',
            'Microsoft YaHei', 'microsoft yahei', '微软雅黑',
            'SimHei', 'simhei', '黑体',
            'NSimSun', 'nsimsun', '新宋体',
            'FangSong', 'fangsong', '仿宋',
            'KaiTi', 'kaiti', '楷体',
            'LiSu', 'lisu', '隶书',
            'YouYuan', 'youyuan', '幼圆',
            'STSong', 'STHeiti', 'STKaiti', 'STFangsong',
            'Adobe Song Std', 'Adobe Heiti Std',
            'Source Han Sans SC', 'Source Han Serif SC',
            'Noto Sans CJK SC', 'Noto Serif CJK SC',
            'WenQuanYi Micro Hei', 'WenQuanYi Zen Hei'
        ]
        
        has_chinese = any(ord(char) > 127 for char in text)
        is_chinese_font = any(cf.lower() in font_family.lower() for cf in chinese_fonts)
        
        if has_chinese or is_chinese_font:
            if is_chinese_font:
                try:
                    return ImageFont.truetype(font_family, font_size)
                except:
                    pass
            
            for font_name in chinese_fonts:
                try:
                    return ImageFont.truetype(font_name, font_size)
                except:
                    continue
        
        try:
            return ImageFont.truetype(font_family, font_size)
        except:
            pass
        
        fallback_fonts = ['Arial', 'Times New Roman', 'Helvetica', 'Verdana']
        for font_name in fallback_fonts:
            try:
                return ImageFont.truetype(font_name, font_size)
            except:
                continue
        
        return ImageFont.load_default()
        
    def update_preview(self):
        if not self.images or self.current_index >= len(self.images):
            return
            
        try:
            img_path = self.images[self.current_index]
            pil_img = Image.open(img_path)
            
            self.original_size = pil_img.size
            
            if pil_img.mode != 'RGBA':
                pil_img = pil_img.convert('RGBA')
            
            label_width = self.image_label.width() - 20
            label_height = self.image_label.height() - 20
            
            img_width, img_height = pil_img.size
            
            scale_w = label_width / img_width
            scale_h = label_height / img_height
            self.preview_scale = min(scale_w, scale_h, 1.0)
            self.image_label.preview_scale = self.preview_scale
            
            if self.preview_scale < 1.0:
                new_size = (int(img_width * self.preview_scale), int(img_height * self.preview_scale))
                preview_img = pil_img.resize(new_size, Image.Resampling.LANCZOS)
            else:
                preview_img = pil_img
                self.preview_scale = 1.0
            
            watermarked = self.apply_watermark_to_preview(preview_img)
            
            qt_image = ImageQt.ImageQt(watermarked)
            pixmap = QPixmap.fromImage(qt_image)
            
            self.image_label.setPixmap(pixmap)
            
            if self.custom_radio.isChecked():
                if self.current_index in self.custom_positions:
                    x, y = self.custom_positions[self.current_index]
                    display_x = int(x * self.preview_scale + (self.image_label.width() - pixmap.width()) // 2)
                    display_y = int(y * self.preview_scale + (self.image_label.height() - pixmap.height()) // 2)
                else:
                    display_x = self.image_label.width() // 2
                    display_y = self.image_label.height() // 2
                self.image_label.set_watermark_position(display_x, display_y)
            
            self.update_file_count()
            
        except Exception as e:
            self.status_bar.showMessage(f"预览错误: {str(e)}")
            
    def apply_watermark_to_preview(self, image):
        img = image.copy()
        width, height = img.size
        
        opacity = self.opacity_slider.value()
        rotation = self.rot_spin.value()
        margin_x = int(self.margin_x_spin.value() * self.preview_scale)
        margin_y = int(self.margin_y_spin.value() * self.preview_scale)
        
        if self.text_radio.isChecked():
            text = self.text_edit.text()
            if not text:
                return img
            
            original_font_size = self.size_spin.value()
            font_size = max(1, int(original_font_size * self.preview_scale))
            
            font_family = self.font_combo.currentText()
            
            font_obj = self.get_font(font_family, font_size, text)
            
            overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(overlay)
            
            bbox = draw.textbbox((0, 0), text, font=font_obj)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            rgb = self.parse_color(self.current_color)
            rgba = rgb + (opacity,)
            
            positions = self.get_positions(width, height, text_width, text_height, margin_x, margin_y)
            
            for x, y in positions:
                if rotation != 0:
                    txt_layer = Image.new('RGBA', (text_width + 20, text_height + 20), (255, 255, 255, 0))
                    txt_draw = ImageDraw.Draw(txt_layer)
                    txt_draw.text((10, 10), text, font=font_obj, fill=rgba)
                    rotated = txt_layer.rotate(-rotation, expand=True)
                    overlay.paste(rotated, (int(x - rotated.width/2 + text_width/2),
                                          int(y - rotated.height/2 + text_height/2)), rotated)
                else:
                    draw.text((x, y), text, font=font_obj, fill=rgba)
            
            img = Image.alpha_composite(img, overlay)
            
        else:
            if not self.watermark_image_path or not os.path.exists(self.watermark_image_path):
                return img
            
            wm = Image.open(self.watermark_image_path).convert("RGBA")
            scale = self.img_scale_slider.value() / 100.0
            scale *= self.preview_scale
            
            new_size = (int(wm.width * scale), int(wm.height * scale))
            if new_size[0] > 0 and new_size[1] > 0:
                wm = wm.resize(new_size, Image.Resampling.LANCZOS)
                
                alpha = wm.split()[-1]
                alpha = alpha.point(lambda p: int(p * opacity / 255))
                wm.putalpha(alpha)
                
                wm_width, wm_height = wm.size
                positions = self.get_positions(width, height, wm_width, wm_height, margin_x, margin_y)
                
                overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
                for x, y in positions:
                    if rotation != 0:
                        rotated_wm = wm.rotate(-rotation, expand=True)
                        overlay.paste(rotated_wm, (int(x), int(y)), rotated_wm)
                    else:
                        overlay.paste(wm, (int(x), int(y)), wm)
                
                img = Image.alpha_composite(img, overlay)
        
        return img
    
    def parse_color(self, color_str):
        try:
            if color_str.startswith('#') and len(color_str) == 7:
                return tuple(int(color_str[i:i+2], 16) for i in (1, 3, 5))
            elif color_str.startswith('#') and len(color_str) == 4:
                return tuple(int(color_str[i]*2, 16) for i in range(1, 4))
            elif color_str.lower() == 'white':
                return (255, 255, 255)
            elif color_str.lower() == 'black':
                return (0, 0, 0)
            elif color_str.lower() == 'red':
                return (255, 0, 0)
            elif color_str.lower() == 'green':
                return (0, 255, 0)
            elif color_str.lower() == 'blue':
                return (0, 0, 255)
            else:
                qcolor = QColor(color_str)
                if qcolor.isValid():
                    return (qcolor.red(), qcolor.green(), qcolor.blue())
                return (255, 255, 255)
        except:
            return (255, 255, 255)
    
    def get_positions(self, img_w, img_h, wm_w, wm_h, margin_x, margin_y):
        positions = []
        
        if self.full_radio.isChecked():
            spacing_x = int(self.spacing_x_spin.value() * self.preview_scale)
            spacing_y = int(self.spacing_y_spin.value() * self.preview_scale)
            
            for y in range(0, img_h, spacing_y):
                for x in range(0, img_w, spacing_x):
                    positions.append((x, y))
        
        elif self.custom_radio.isChecked():
            if self.current_index in self.custom_positions:
                x, y = self.custom_positions[self.current_index]
                x = int(x * self.preview_scale)
                y = int(y * self.preview_scale)
                positions.append((x, y))
            else:
                positions.append((img_w//2 - wm_w//2, img_h//2 - wm_h//2))
        
        else:
            preset_defs = {
                'top_left': (margin_x, margin_y),
                'top_center': (img_w//2 - wm_w//2, margin_y),
                'top_right': (img_w - wm_w - margin_x, margin_y),
                'center_left': (margin_x, img_h//2 - wm_h//2),
                'center': (img_w//2 - wm_w//2, img_h//2 - wm_h//2),
                'center_right': (img_w - wm_w - margin_x, img_h//2 - wm_h//2),
                'bottom_left': (margin_x, img_h - wm_h - margin_y),
                'bottom_center': (img_w//2 - wm_w//2, img_h - wm_h - margin_y),
                'bottom_right': (img_w - wm_w - margin_x, img_h - wm_h - margin_y)
            }
            
            for pos_key, chk in self.position_checks.items():
                if chk.isChecked():
                    positions.append(preset_defs[pos_key])
        
        return positions if positions else [(img_w//2 - wm_w//2, img_h//2 - wm_h//2)]
    
    def start_processing(self):
        if not self.images:
            QMessageBox.warning(self, "警告", "请先添加图片")
            return
        
        if self.output_over_radio.isChecked():
            reply = QMessageBox.question(self, "确认", "确定要覆盖原文件吗？此操作不可恢复！",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        settings = {
            'watermark_type': 'text' if self.text_radio.isChecked() else 'image',
            'text': self.text_edit.text(),
            'font_family': self.font_combo.currentText(),
            'font_size': self.size_spin.value(),
            'color': self.current_color,
            'opacity': self.opacity_slider.value(),
            'rotation': self.rot_spin.value(),
            'margin_x': self.margin_x_spin.value(),
            'margin_y': self.margin_y_spin.value(),
            'position_mode': 'preset',
            'positions': [k for k, v in self.position_checks.items() if v.isChecked()],
            'spacing_x': self.spacing_x_spin.value(),
            'spacing_y': self.spacing_y_spin.value(),
            'image_scale': self.img_scale_slider.value() / 100.0,
            'watermark_image_path': self.watermark_image_path,
            'output_mode': 'new' if self.output_new_radio.isChecked() else 'overwrite',
            'output_format': self.format_combo.currentText(),
            'quality': self.quality_spin.value()
        }
        
        if self.full_radio.isChecked():
            settings['position_mode'] = 'full'
        elif self.custom_radio.isChecked():
            settings['position_mode'] = 'custom'
        
        self.start_btn.setEnabled(False)
        self.start_btn.setText("处理中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(self.images))
        self.progress_bar.setValue(0)
        
        self.worker = WatermarkWorker(self.images, settings)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()
    
    def on_progress(self, current, total, filename):
        self.progress_bar.setValue(current)
        self.status_bar.showMessage(f"正在处理 {current}/{total}: {filename}")
    
    def on_finished(self, success, fail):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 开始批量处理")
        self.progress_bar.setVisible(False)
        
        QMessageBox.information(self, "完成", f"处理完成！\n成功: {success} 张\n失败: {fail} 张")
        self.status_bar.showMessage(f"处理完成 - 成功: {success}, 失败: {fail}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    
    window = WatermarkApp()
    window.show()
    sys.exit(app.exec())