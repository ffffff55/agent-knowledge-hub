# 鹈鹕骑自行车动画实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个可离线打开的 HTML 页面，以 SVG 绘制并循环播放鹈鹕骑自行车的 2D 动画。

**Architecture:** 将页面、样式、内嵌 SVG 场景和少量暂停控制逻辑全部放在 `python/web/pelican-bike.html`。用 SVG 图层与 CSS keyframes 分别驱动车轮、曲柄、骑行者和海岸背景；用媒体查询尊重减少动态效果设置。

**Tech Stack:** HTML5、内嵌 SVG、CSS animations、原生 JavaScript；结构测试使用 Python 标准库 `unittest` 和 `html.parser`。

---

## 文件结构

- Create: `python/web/pelican-bike.html`，唯一的用户交付页面；不引用外部资源。
- Create: `python/tests/test_pelican_bike_html.py`，检查页面语义、SVG 场景、可访问控制、动效偏好和无外部资源。
- Do not modify: `python/web/index.html` 及当前工作区其他已有或未提交文件。

### Task 1：先建立页面结构回归测试

**Files:**
- Create: `python/tests/test_pelican_bike_html.py`

- [ ] **Step 1: 编写结构测试**

用 `HTMLParser` 收集标签、属性、ID、外部资源引用和 SVG 图元；测试断言 `lang="zh-CN"`、viewport、唯一 ID、含有 SVG `title`/`desc` 及足够的图元、可访问的暂停按钮、减少动态效果规则，并且没有外部 URL。

- [ ] **Step 2: 运行测试，确认因页面尚不存在而失败**

Run: `python -m unittest python.tests.test_pelican_bike_html -v`
Expected: FAIL，页面文件不存在。

### Task 2：绘制独立的海岸骑行场景

**Files:**
- Create: `python/web/pelican-bike.html`

- [ ] **Step 1: 编写完整的响应式 HTML 外壳和内嵌 SVG**

使用 `viewBox="0 0 1080 680"` 与 `preserveAspectRatio="xMidYMid meet"`。SVG 使用 `role="img"`、`aria-labelledby`、`title` 和 `desc`。场景至少包含天空、海岸/地面、云、植被、两只带辐条的车轮、珊瑚色车架、车座/把手/曲柄、鹈鹕身体/翅膀/长喙/喉囊/眼睛/双腿。用清晰轮廓和蓝绿、珊瑚橙、黄色、深色线稿构成绘本感，主体在宽屏和窄屏都完整落入 viewBox。

- [ ] **Step 2: 给 SVG 活动部件添加独立动画类**

为轮组、曲柄、骑行者身体、喉囊和地面细节分别定义稳定的 SVG 分组与 transform-origin；CSS keyframes 以无跳变循环驱动轮组旋转、踩踏和轻微身体起伏，地面移动幅度保持克制。

### Task 3：完成控制、动效偏好与验证

**Files:**
- Modify: `python/web/pelican-bike.html`
- Test: `python/tests/test_pelican_bike_html.py`

- [ ] **Step 1: 增加键盘可操作的暂停/继续控制**

加入一个 `type="button"`、有 `aria-label` 与 `aria-pressed` 的控件。原生 JavaScript 在点击时切换 SVG 场景的暂停状态、可见命令文字、按钮标签与 pressed 状态；焦点样式清楚可见。

- [ ] **Step 2: 实现减少动态效果与窄屏布局**

在 `@media (prefers-reduced-motion: reduce)` 中禁用持续动画；JavaScript 监听偏好变化，匹配时保持静态插画并禁用暂停/继续控件，偏好取消后恢复控件。用弹性宽度和固定 SVG viewBox 避免横向溢出。

- [ ] **Step 3: 运行结构测试并检查页面**

Run: `python -m unittest python.tests.test_pelican_bike_html -v`
Expected: 全部 PASS。

直接在浏览器打开 `python/web/pelican-bike.html`，检查桌面和窄屏画面、轮转和踩踏、暂停/继续、键盘焦点、减少动态效果偏好以及控制台错误。确认文件没有外部请求。

- [ ] **Step 4: 只提交本任务新增的页面和测试**

```powershell
git add -- python/web/pelican-bike.html python/tests/test_pelican_bike_html.py
git commit -m "feat: add animated pelican bicycle page"
```
