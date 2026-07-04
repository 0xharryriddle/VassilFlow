import { cn } from "@/lib/utils";

export function Section({
  className,
  title,
  subtitle,
  children,
}: {
  className?: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("mx-auto flex w-full flex-col py-20", className)}>
      <header className="flex flex-col items-center justify-between">
        <div className="mb-4 max-w-4xl text-center text-4xl font-semibold tracking-tight text-white md:text-5xl">
          {title}
        </div>
        {subtitle && (
          <div className="text-muted-foreground max-w-3xl text-center text-lg leading-8">
            {subtitle}
          </div>
        )}
      </header>
      <main className="mt-4">{children}</main>
    </section>
  );
}
