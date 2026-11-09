/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // exceljs is large; it is only imported dynamically in the browser when someone clicks "Download Excel"
};
export default nextConfig;
