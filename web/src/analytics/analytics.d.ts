// 第三方库类型声明

declare module 'analytics' {
    export interface AnalyticsInstance {
        track: (eventName: string, properties?: Record<string, unknown>) => void
        page: (properties?: Record<string, unknown>) => void
        identify: (userId: string, traits?: Record<string, unknown>) => void
        reset: () => void
        user: () => Record<string, unknown>
        ready: (callback: () => void) => void
        on: (event: string, callback: (...args: unknown[]) => void) => void
        once: (event: string, callback: (...args: unknown[]) => void) => void
        getState: () => Record<string, unknown>
        storage: {
            getItem: (key: string) => unknown
            setItem: (key: string, value: unknown) => void
            removeItem: (key: string) => void
        }
        plugins: Record<string, unknown>
    }

    export interface AnalyticsPlugin {
        name: string
        initialize?: () => void | Promise<void>
        track?: (params: { payload: { event: string; properties?: Record<string, unknown> } }) => void
        page?: (params: { payload: { properties?: Record<string, unknown> } }) => void
        identify?: (params: { payload: { userId: string; traits?: Record<string, unknown> } }) => void
        loaded?: () => boolean
    }

    export interface AnalyticsConfig {
        app: string
        debug?: boolean
        plugins?: AnalyticsPlugin[]
    }

    export default function Analytics(config: AnalyticsConfig): AnalyticsInstance
}

declare module '@analytics/google-analytics' {
    import type { AnalyticsPlugin } from 'analytics'

    export interface GoogleAnalyticsConfig {
        measurementIds: string[]
        debug?: boolean
        dataLayerName?: string
        gtagName?: string
        gtagConfig?: Record<string, unknown>
    }

    export default function googleAnalytics(config: GoogleAnalyticsConfig): AnalyticsPlugin
}
