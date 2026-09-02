# 图片嵌入测试用例

覆盖 docx / doc / wps 三种可嵌入图片格式：图片来源包括相对路径、
绝对路径、data URI；尺寸覆盖宽图 / 小图 / 超高图 / 中图，验证
「先下载（读取）→ 嵌入真实图片 → 等比缩放不超出版心宽/高 → 居中」。

## 块级图片

![宽图 2400x300](assets/wide.png)

![小图 96x64](assets/small.png)

![超高图 200x1600](assets/tall.png)

![中图 900x500](assets/mid.png)

## 行内图片

正文里夹一张 ![小图](assets/small.png) 作为行内图，随文字排版。

- 列表项里 ![中图](assets/mid.png) 的图片

## 加载失败降级

![不存在的图片](assets/no-such-file.png)

![data URI 图片](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==)
