import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker（multi-stage・軽量ランタイム）向けに standalone 出力を有効化する。
  // .next/standalone に server.js と必要な node_modules だけが吐き出される（DEPLOY.md 参照）。
  output: "standalone",
};

export default nextConfig;
