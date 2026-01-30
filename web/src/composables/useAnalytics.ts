import { analytics, trackEvent, trackPage } from '@/analytics'

export type EventProperties = Record<string, string | number | boolean>

export interface UseAnalyticsReturn {
    trackEvent: (eventName: string, properties?: EventProperties) => void
    trackPage: (path: string, title?: string) => void
    analytics: typeof analytics
}

export function useAnalytics(): UseAnalyticsReturn {
    return { trackEvent, trackPage, analytics }
}

export default useAnalytics
