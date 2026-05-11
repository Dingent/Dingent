import { useMemo } from "react";

const base64ToBlob = (base64: string): Blob => {
  const arr = base64.split(",");
  const mimeMatch = arr[0].match(/:(.*?);/);
  const mime = mimeMatch ? mimeMatch[1] : "image/png";
  const bstr = atob(arr[1]);
  let n = bstr.length;
  const u8arr = new Uint8Array(n);
  while (n--) {
    u8arr[n] = bstr.charCodeAt(n);
  }
  return new Blob([u8arr], { type: mime });
};
export function useOptimizedMarkdown(rawContent: string) {
  // 使用 useMemo 缓存处理结果
  return useMemo(() => {
    if (!rawContent) return rawContent;

    // 正则匹配 Markdown 图片语法: ![alt](data:image/...)
    // 捕获组 1: alt 文本
    // 捕获组 2: base64 数据
    const regex = /!\[(.*?)\]\((data:image\/.*?;base64,.*?)\)/g;

    let lastIndex = 0;
    let newContent = "";
    let match;

    // 用于存储生成的 Blob URL，以便后续清理（可选，通常 React 组件卸载时不手动清理也会被 GC，但在大量图片时建议清理）
    // 这里为了简单，我们直接替换字符串。
    // 如果你在流式输出中，这个 useMemo 会频繁执行，这是一个权衡。

    // 更好的策略：
    // 实际上，流式传输时，Base64 往往还没传完，正则可能匹配不到。
    // 但一旦传完，正则匹配并替换为 Blob URL。

    newContent = rawContent.replace(regex, (match, alt, base64) => {
      try {
        const blob = base64ToBlob(base64);
        const blobUrl = URL.createObjectURL(blob);
        return `![${alt}](${blobUrl})`;
      } catch (e) {
        // 如果转换失败（例如 Base64 不完整），保持原样
        console.warn("Base64 optimization failed", e);
        return match;
      }
    });

    return newContent;
  }, [rawContent]);
}
