from managers.ocr_manager import ocr
from managers.logger_manager import logger
from managers.translate_manager import _

import numpy as np
import time
import math
import cv2

from .input import Input
from .screenshot import Screenshot


class Automation:
    _instance = None

    def __new__(cls, window_title):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.window_title = window_title
            cls._instance.screenshot = None
            cls._instance.init_automation()

        return cls._instance

    # 兼容旧代码
    def init_automation(self):
        self.mouse_click = Input.mouse_click
        self.mouse_down = Input.mouse_down
        self.mouse_up = Input.mouse_up
        self.mouse_move = Input.mouse_move
        self.mouse_scroll = Input.mouse_scroll
        self.press_key = Input.press_key
        self.press_mouse = Input.press_mouse

    def take_screenshot(self, crop=(0, 0, 1, 1)):
        result = Screenshot.take_screenshot(self.window_title, crop=crop)
        if result:
            self.screenshot, self.screenshot_pos, self.screenshot_scale_factor, self.real_width = result
        return result

    def get_image_info(self, image_path):
        template = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        return template.shape[::-1]

    def scale_and_match_template(self, screenshot, template, threshold=None, scale_range=None):
        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if (threshold is None or max_val < threshold) and scale_range is not None:
            for scale in np.arange(scale_range[0], scale_range[1] + 0.0001, 0.05):
                scaled_template = cv2.resize(template, None, fx=scale, fy=scale)
                result = cv2.matchTemplate(screenshot, scaled_template, cv2.TM_CCOEFF_NORMED)
                _, local_max_val, _, local_max_loc = cv2.minMaxLoc(result)

                if local_max_val > max_val:
                    max_val = local_max_val
                    max_loc = local_max_loc

        return max_val, max_loc

    def find_element(self, target, find_type, threshold=None, max_retries=1, crop=(0, 0, 1, 1), take_screenshot=True, relative=False, scale_range=None, include=None, need_ocr=True, source=None, source_type=None, pixel_bgr=None):
        # 参数有些太多了，以后改（大概是懒得改了）
        take_screenshot = False if not need_ocr else take_screenshot
        max_retries = 1 if not take_screenshot else max_retries
        for i in range(max_retries):
            if take_screenshot and not self.take_screenshot(crop):
                continue
            if find_type in ['image', 'image_threshold', 'text', "min_distance_text"]:
                if find_type in ['image', 'image_threshold']:
                    top_left, bottom_right, image_threshold = self.find_image_element(
                        target, threshold, scale_range, relative)
                elif find_type == 'text':
                    top_left, bottom_right = self.find_text_element(
                        target, include, need_ocr, relative)
                elif find_type == 'min_distance_text':
                    top_left, bottom_right = self.find_min_distance_text_element(
                        target, source, source_type, include, need_ocr)
                if top_left and bottom_right:
                    if find_type == 'image_threshold':
                        return image_threshold
                    return top_left, bottom_right
            elif find_type in ['image_count']:
                return self.find_image_and_count(target, threshold, pixel_bgr)
            else:
                raise ValueError(_("错误的类型"))

            if i < max_retries - 1:
                time.sleep(1)
        return None

    def find_image_element(self, target, threshold, scale_range, relative=False):
        try:
            # template = cv2.imread(target, cv2.IMREAD_GRAYSCALE)
            template = cv2.imread(target)
            if template is None:
                raise ValueError(_("读取图片失败"))

            if self.real_width < 1920:
                screenshot_scale_factor = 1920 / self.real_width
                # 获取模板的原始宽度和高度
                template_height, template_width = template.shape[:2]
                # 缩放模板
                template = cv2.resize(template, (int(template_width / screenshot_scale_factor), int(template_height / screenshot_scale_factor)))

            # screenshot = cv2.cvtColor(np.array(self.screenshot), cv2.COLOR_BGR2GRAY)
            screenshot = cv2.cvtColor(np.array(self.screenshot), cv2.COLOR_BGR2RGB)
            max_val, max_loc = self.scale_and_match_template(screenshot, template, threshold, scale_range)
            logger.debug(_("目标图片：{target} 相似度：{max_val}").format(target=target, max_val=max_val))
            if threshold is None or max_val >= threshold:
                channels, width, height = template.shape[::-1]
                if relative == False:
                    top_left = (int(max_loc[0] / self.screenshot_scale_factor) + self.screenshot_pos[0],
                                int(max_loc[1] / self.screenshot_scale_factor) + self.screenshot_pos[1])
                else:
                    top_left = (int(max_loc[0] / self.screenshot_scale_factor), int(max_loc[1] / self.screenshot_scale_factor))
                bottom_right = (top_left[0] + int(width / self.screenshot_scale_factor), top_left[1] + int(height / self.screenshot_scale_factor))
                return top_left, bottom_right, max_val
        except Exception as e:
            logger.error(_("寻找图片出错：{e}").format(e=e))
        return None, None, None

    @staticmethod
    def intersected(top_left1, botton_right1, top_left2, botton_right2):
        if top_left1[0] > botton_right2[0] or top_left2[0] > botton_right1[0]:
            return False
        if top_left1[1] > botton_right2[1] or top_left2[1] > botton_right1[1]:
            return False
        return True

    @staticmethod
    def count_template_matches(target, template, threshold):
        result = cv2.matchTemplate(target, template, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)
        match_count = 0
        matches = []
        width, height = template.shape[::-1]
        for top_left in zip(*locations[::-1]):
            flag = True
            for match_top_left in matches:
                botton_right = (top_left[0] + width, top_left[1] + height)
                match_botton_right = (match_top_left[0] + width, match_top_left[1] + height)
                is_intersected = Automation.intersected(
                    top_left, botton_right, match_top_left, match_botton_right)
                if is_intersected:
                    flag = False
                    break
            if flag == True:
                matches.append(top_left)
                match_count += 1
        return match_count

    def find_image_and_count(self, target, threshold, pixel_bgr):
        try:
            template = cv2.imread(target, cv2.IMREAD_GRAYSCALE)
            if template is None:
                raise ValueError(_("读取图片失败"))

            if self.real_width < 1920:
                screenshot_scale_factor = 1920 / self.real_width
                # 获取模板的原始宽度和高度
                template_height, template_width = template.shape[:2]
                # 缩放模板
                template = cv2.resize(template, (int(template_width / screenshot_scale_factor), int(template_height / screenshot_scale_factor)))

            screenshot = cv2.cvtColor(np.array(self.screenshot), cv2.COLOR_BGR2RGB)
            bw_map = np.zeros(screenshot.shape[:2], dtype=np.uint8)
            # 遍历每个像素并判断与目标像素的相似性
            bw_map[np.sum((screenshot - pixel_bgr) ** 2, axis=-1) <= 800] = 255
            # cv2.imwrite("test.png", bw_map)
            # cv2.imshow("test", np.array(bw_map))
            # cv2.waitKey(0)
            # cv2.destroyAllWindows()
            return Automation.count_template_matches(bw_map, template, threshold)
        except Exception as e:
            logger.error(_("寻找图片并计数出错：{e}").format(e=e))
            return None

    def find_text_element(self, target, include, need_ocr=True, relative=False):
        # 兼容旧代码
        if isinstance(target, str):
            target = (target,)
        try:
            if need_ocr:
                self.ocr_result = ocr.recognize_multi_lines(np.array(self.screenshot))
            if not self.ocr_result:
                logger.debug(_("目标文字：{target} 未找到，没有识别出任何文字").format(target=", ".join(target)))
                return None, None
            for box in self.ocr_result:
                text = box[1][0]
                # if (include is None and target == text) or (include and target in text) or (not include and target == text):
                if ((include is None or not include) and text in target) or (include and any(t in text for t in target)):
                    self.matched_text = next((t for t in target if t in text), None)
                    logger.debug(_("目标文字：{target} 相似度：{max_val}").format(
                        target=self.matched_text, max_val=box[1][1]))
                    if relative == False:
                        top_left = (int(box[0][0][0] / self.screenshot_scale_factor) + self.screenshot_pos[0],
                                    int(box[0][0][1] / self.screenshot_scale_factor) + self.screenshot_pos[1])
                        bottom_right = (int(box[0][2][0] / self.screenshot_scale_factor) + self.screenshot_pos[0],
                                        int(box[0][2][1] / self.screenshot_scale_factor) + self.screenshot_pos[1])
                    else:
                        top_left = (int(box[0][0][0] / self.screenshot_scale_factor), int(box[0][0][1] / self.screenshot_scale_factor))
                        bottom_right = (int(box[0][2][0] / self.screenshot_scale_factor), int(box[0][2][1] / self.screenshot_scale_factor))
                    return top_left, bottom_right
            logger.debug(_("目标文字：{target} 未找到，没有识别出匹配文字").format(target=", ".join(target)))
            return None, None
        except Exception as e:
            logger.error(_("寻找文字：{target} 出错：{e}").format(target=", ".join(target), e=e))
            return None, None

    def find_min_distance_text_element(self, target, source, source_type, include, need_ocr=True):
        if need_ocr:
            self.ocr_result = ocr.recognize_multi_lines(np.array(self.screenshot))
        source_pos = None

        if source_type == 'text':
            if not self.ocr_result:
                logger.debug(_("目标文字：{source} 未找到，没有识别出任何文字").format(source=source))
                return None, None
            # logger.debug(self.ocr_result)
            for box in self.ocr_result:
                text = box[1][0]
                if ((include is None or not include) and source == text) or (include and source in text):
                    logger.debug(_("目标文字：{source} 相似度：{max_val}").format(
                        source=source, max_val=box[1][1]))
                    source_pos = box[0][0]
                    break
        elif source_type == 'image':
            source_pos, i, i = self.find_image_element(source, 0.7, None, True)

        if source_pos is None:
            logger.debug(_("目标内容：{source} 未找到").format(source=source))
            return None, None
        else:
            logger.debug(_("目标内容：{source} 坐标：{source_pos}").format(source=source, source_pos=source_pos))

        # 兼容旧代码
        if isinstance(target, str):
            target = (target,)
        target_pos = None
        min_distance = float('inf')
        for box in self.ocr_result:
            text = box[1][0]
            if ((include is None or not include) and text in target) or (include and any(t in text for t in target)):
                matched_text = next((t for t in target if t in text), None)
                pos = box[0]
                # 如果target不在source右下角
                if not ((pos[0][0] - source_pos[0]) > 0 and (pos[0][1] - source_pos[1]) > 0):
                    continue
                distance = math.sqrt((pos[0][0] - source_pos[0]) **
                                     2 + (pos[0][1] - source_pos[1]) ** 2)
                logger.debug(_("目标文字：{target} 相似度：{max_val} 距离：{min_distance}").format(
                    target=matched_text, max_val=box[1][1], min_distance=distance))
                if distance < min_distance:
                    min_target = matched_text
                    min_distance = distance
                    target_pos = pos
        if target_pos is None:
            logger.debug(_("目标文字：{target} 未找到，没有识别出匹配文字").format(target=", ".join(target)))
            return None, None
        logger.debug(_("目标文字：{target} 最短距离：{min_distance}").format(
            target=min_target, min_distance=min_distance))
        top_left = (int(target_pos[0][0] / self.screenshot_scale_factor) + self.screenshot_pos[0],
                    int(target_pos[0][1] / self.screenshot_scale_factor) + self.screenshot_pos[1])
        bottom_right = (int(target_pos[2][0] / self.screenshot_scale_factor) + self.screenshot_pos[0],
                        int(target_pos[2][1] / self.screenshot_scale_factor) + self.screenshot_pos[1])
        return top_left, bottom_right

    def click_element_with_pos(self, coordinates, offset=(0, 0), action="click"):
        (left, top), (right, bottom) = coordinates
        x = (left + right) // 2 + offset[0]
        y = (top + bottom) // 2 + offset[1]
        if action == "click":
            self.mouse_click(x, y)
        elif action == "down":
            self.mouse_down(x, y)
        elif action == "move":
            self.mouse_move(x, y)
        return True

    def click_element(self, target, find_type, threshold=None, max_retries=1, crop=(0, 0, 1, 1), take_screenshot=True, relative=False, scale_range=None, include=None, need_ocr=True, source=None, source_type=None, offset=(0, 0), action="click"):
        coordinates = self.find_element(target, find_type, threshold, max_retries, crop, take_screenshot,
                                        relative, scale_range, include, need_ocr, source, source_type)
        if coordinates:
            return self.click_element_with_pos(coordinates, offset, action)
        return False

    def get_single_line_text(self, crop=(0, 0, 1, 1), blacklist=None, max_retries=3):
        for i in range(max_retries):
            self.take_screenshot(crop)
            ocr_result = ocr.recognize_single_line(np.array(self.screenshot), blacklist)
            if ocr_result:
                return ocr_result[0]
        return None

    def retry_with_timeout(self, lambda_func, timeout=120, interval=1):
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                result = lambda_func()
                if result:
                    return result
            except Exception as e:
                logger.error(e)

            time.sleep(interval)

        return False
