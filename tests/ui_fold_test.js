/* Md2docs 折叠面板 UI 逻辑测试（jsdom） */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("C:/Users/Dell/node_modules/jsdom");

const ROOT = path.join(__dirname, "..");
const htmlSrc = fs.readFileSync(path.join(ROOT, "src", "web", "index.html"), "utf-8");
const jsSrc = fs.readFileSync(path.join(ROOT, "src", "web", "assets", "app.js"), "utf-8");

const config = {
  ok: true,
  workdir: "C:\\Users\\Dell\\Documents\\Md2docs",
  default_out: "C:\\Users\\Dell\\Documents\\Md2docs\\转换结果",
  formats: [
    { id: "docx", ext: ".docx", label: "Word 文档 (.docx)" },
    { id: "doc", ext: ".doc", label: "Word 97-2003 (.doc)" },
    { id: "wps", ext: ".wps", label: "WPS 文字 (.wps)" },
    { id: "txt", ext: ".txt", label: "纯文本 (.txt)" },
  ],
  caps: { word: false, wps: true },
  encodings: ["utf-8", "utf-8-bom", "gbk"],
};

const dom = new JSDOM(htmlSrc, {
  runScripts: "dangerously",
  url: "http://127.0.0.1:9/",
  beforeParse(window) {
    window.fetch = async (url) => {
      const p = String(url);
      if (p.endsWith("/api/config")) return { ok: true, json: async () => config };
      if (p.endsWith("/api/heartbeat") || p.endsWith("/api/page-closed"))
        return { ok: true, json: async () => ({ ok: true }) };
      throw new Error("unexpected fetch " + p);
    };
    window.navigator.sendBeacon = () => true;
  },
});

const { window } = dom;
const doc = window.document;
window.eval(jsSrc); // 页面就绪后注入应用逻辑

const q1 = (s) => doc.querySelector(s);
const qa = (s) => Array.from(doc.querySelectorAll(s));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, cond) {
  results.push({ name, pass: !!cond });
  console.log((cond ? "PASS" : "FAIL") + "  " + name);
}

(async () => {
  await sleep(150); // 等 init 完成

  check("默认输出模式为 same",
    qa('input[name="outMode"]').find((r) => r.checked).value === "same");
  check("foldOutDir 默认折叠", !q1("#foldOutDir").classList.contains("open"));
  check("foldTxt 默认折叠", !q1("#foldTxt").classList.contains("open"));
  check("foldNative 默认折叠", !q1("#foldNative").classList.contains("open"));
  check("输出位置摘要=与源文件相同", q1("#foldOutDirSum").textContent === "与源文件相同");
  check("native 摘要=RTF 兼容格式", q1("#foldNativeSum").textContent.includes("RTF"));
  check("native 开关启用(WPS 已就绪)", q1("#nativeMode").disabled === false);
  check("格式卡片已渲染 4 项", qa(".fmt").length === 4);

  // 勾选 TXT → 自动展开
  qa(".fmt").find((el) => el.dataset.id === "txt").click();
  await sleep(60);
  check("勾选 TXT 后 foldTxt 自动展开", q1("#foldTxt").classList.contains("open"));
  check("TXT 标签变为已选", q1("#foldTxtTag").textContent.includes("已选 TXT"));

  // 点折叠头展开/收起输出位置
  q1("#foldOutDirHead").click();
  await sleep(30);
  check("点击折叠头展开 foldOutDir", q1("#foldOutDir").classList.contains("open"));
  q1("#foldOutDirHead").click();
  await sleep(30);
  check("再次点击收起 foldOutDir", !q1("#foldOutDir").classList.contains("open"));

  // 展开后切 custom
  q1("#foldOutDirHead").click();
  qa('input[name="outMode"]').find((r) => r.value === "custom").click();
  await sleep(30);
  check("切指定目录后输入框启用", !q1("#outDir").disabled);
  check("摘要含 指定目录", q1("#foldOutDirSum").textContent.includes("指定目录"));
  check("浏览按钮启用", !q1("#btnPickDir").disabled);

  // 取消 TXT → 自动收起
  qa(".fmt").find((el) => el.dataset.id === "txt").click();
  await sleep(60);
  check("取消 TXT 后 foldTxt 自动收起", !q1("#foldTxt").classList.contains("open"));

  // 高质量模式开关切换摘要
  q1("#nativeMode").click();
  await sleep(30);
  check("开启高质量模式后摘要更新", q1("#foldNativeSum").textContent.includes("高质量模式"));

  // 作者栏
  check("页脚作者信息存在", q1(".site-foot") && q1(".site-foot").textContent.includes("王冠"));
  check("无退出程序按钮", !q1("#btnQuit"));

  const fails = results.filter((r) => !r.pass).length;
  console.log(`\n${results.length - fails}/${results.length} 通过`);
  process.exit(fails ? 1 : 0);
})();
