/**
 * Analytics module - extensible tracking system
 * Supports multiple providers: Umami, Google Analytics, etc.
 */

import Analytics from 'analytics'
import googleAnalytics from '@analytics/google-analytics'
import { umamiPlugin } from './plugins/umami'

export type { EventProperties, PageViewEvent, AnalyticsEvent } from './types'
export { umamiPlugin, type UmamiPluginConfig } from './plugins'

export const analytics = Analytics({
    app: 'imgtag',
    debug: import.meta.env.DEV,
    plugins: [
        umamiPlugin({
            websiteId: import.meta.env.VITE_UMAMI_WEBSITE_ID,
            host: import.meta.env.VITE_UMAMI_HOST,
            autoTrack: true,
        }),
        ...(import.meta.env.VITE_GA_MEASUREMENT_ID
            ? [googleAnalytics({ measurementIds: [import.meta.env.VITE_GA_MEASUREMENT_ID] })]
            : []),
    ],
})

export function initAnalytics(): void {
    if (import.meta.env.DEV) {
        console.log('[Analytics] Initialized:', {
            umami: !!import.meta.env.VITE_UMAMI_WEBSITE_ID,
            ga: !!import.meta.env.VITE_GA_MEASUREMENT_ID,
        })
    }
}

export function trackEvent(
    eventName: string,
    properties?: Record<string, string | number | boolean>
): void {
    analytics.track(eventName, properties)
}

export function trackPage(path: string, title?: string): void {
    analytics.page({ path, title })
}

export default analytics
