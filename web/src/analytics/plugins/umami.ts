/**
 * Umami Analytics Plugin
 * @see https://umami.is/docs
 */

import type { AnalyticsPlugin } from 'analytics'
import type { EventProperties, PageProperties } from '../types'

export interface UmamiPluginConfig {
    websiteId?: string
    host?: string
    autoTrack?: boolean
    domains?: string[]
}

export function umamiPlugin(config: UmamiPluginConfig = {}): AnalyticsPlugin {
    const { websiteId, host, autoTrack = true, domains } = config

    return {
        name: 'umami',

        initialize: () => {
            if (!websiteId || !host) return
            if (document.querySelector(`script[data-website-id="${websiteId}"]`)) return

            const script = document.createElement('script')
            script.async = true
            script.defer = true
            script.src = `${host}/script.js`
            script.setAttribute('data-website-id', websiteId)
            if (!autoTrack) script.setAttribute('data-auto-track', 'false')
            if (domains?.length) script.setAttribute('data-domains', domains.join(','))
            document.head.appendChild(script)
        },

        track: ({ payload }: { payload: { event: string; properties?: EventProperties } }) => {
            window.umami?.track(payload.event, payload.properties)
        },

        page: ({ payload }: { payload: { properties?: PageProperties } }) => {
            window.umami?.track((props) => ({
                ...props,
                url: payload.properties?.path || payload.properties?.url,
                title: payload.properties?.title,
            }))
        },

        loaded: () => !!window.umami,
    }
}

export default umamiPlugin
