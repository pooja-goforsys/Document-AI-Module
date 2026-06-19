import type { TimelineEvent } from '@/types'

interface Props {
  events: TimelineEvent[]
}

export function AITimelineResponse({ events }: Props) {
  if (!events.length) return null

  return (
    <div className="my-3 rounded-xl border bg-card overflow-hidden">
      <div className="px-4 py-2.5 border-b bg-muted/30">
        <p className="text-xs font-semibold text-foreground/80">Timeline</p>
      </div>
      <div className="px-4 py-3">
        <ol className="relative border-l border-primary/30 ml-2 space-y-4">
          {events.map((ev, i) => (
            <li key={i} className="ml-5">
              {/* Circle on the line */}
              <span className="absolute -left-[9px] flex h-[18px] w-[18px] items-center justify-center rounded-full bg-primary/15 border-2 border-primary/40">
                <span className="h-1.5 w-1.5 rounded-full bg-primary" />
              </span>

              <div className="flex flex-col gap-0.5">
                <span className="text-[11px] font-semibold text-primary leading-none">
                  {ev.date}
                </span>
                <p className="text-[13px] text-foreground leading-snug">{ev.event}</p>
                {ev.description && (
                  <p className="text-[11px] text-muted-foreground leading-relaxed mt-0.5">
                    {ev.description}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}
