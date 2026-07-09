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
    <section
      className={cn("mx-auto flex w-full min-w-0 flex-col py-16", className)}
    >
      <header className="flex flex-col items-center justify-between px-4">
        <div className="mb-4 max-w-full text-center text-3xl font-semibold break-words text-white sm:text-4xl md:text-5xl">
          {title}
        </div>
        {subtitle && (
          <div className="text-muted-foreground max-w-3xl text-center text-base leading-7 break-words sm:text-lg sm:leading-8">
            {subtitle}
          </div>
        )}
      </header>
      <main className="mt-4 w-full min-w-0 px-4">{children}</main>
    </section>
  );
}
