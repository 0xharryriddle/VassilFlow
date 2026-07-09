import "katex/dist/katex.min.css";
import "@/styles/globals.css";

import { type Metadata } from "next";

import { ThemeProvider } from "@/components/theme-provider";
import { APP_BRAND_DESCRIPTION, APP_BRAND_NAME } from "@/core/brand";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

const devPerformanceMeasureGuard = `
(() => {
  try {
    const perf = window.performance;
    if (!perf || perf.__vassilflowMeasureGuardInstalled) return;
    const measure = perf.measure.bind(perf);

    Object.defineProperty(perf, "__vassilflowMeasureGuardInstalled", {
      value: true,
    });

    perf.measure = (name, startOrMeasureOptions, endMark) => {
      if (
        startOrMeasureOptions &&
        typeof startOrMeasureOptions === "object"
      ) {
        const options = { ...startOrMeasureOptions };
        if (typeof options.start === "number" && options.start < 0) {
          options.start = 0;
        }
        if (typeof options.end === "number" && options.end < 0) {
          options.end = 0;
        }
        if (typeof options.duration === "number" && options.duration < 0) {
          options.duration = 0;
        }
        if (
          typeof options.start === "number" &&
          typeof options.end === "number" &&
          options.end < options.start
        ) {
          options.end = options.start;
        }
        return measure(name, options);
      }
      return measure(name, startOrMeasureOptions, endMark);
    };
  } catch {}
})();
`;

export const metadata: Metadata = {
  title: APP_BRAND_NAME,
  description: APP_BRAND_DESCRIPTION,
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await detectLocaleServer();
  return (
    <html lang={locale} suppressContentEditableWarning suppressHydrationWarning>
      <body>
        {process.env.NODE_ENV !== "production" ? (
          <script
            id="vassilflow-performance-measure-guard"
            dangerouslySetInnerHTML={{ __html: devPerformanceMeasureGuard }}
          />
        ) : null}
        <ThemeProvider attribute="class" enableSystem disableTransitionOnChange>
          <I18nProvider initialLocale={locale}>{children}</I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
