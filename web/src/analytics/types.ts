export interface EventProperties {
    [key: string]: string | number | boolean | undefined
}

export interface PageProperties {
    path?: string
    title?: string
    referrer?: string
    url?: string
}

export interface AnalyticsEvent {
    name: string
    properties?: EventProperties
}

export interface PageViewEvent {
    path: string
    title?: string
}

declare global {
    interface Window {
        umami?: {
            track: (
                event: string | ((props: Record<string, unknown>) => Record<string, unknown>),
                data?: EventProperties
            ) => void
        }
        dataLayer?: unknown[]
        gtag?: (...args: unknown[]) => void
    }
}

export { }
