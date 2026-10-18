import { useQuery } from '@tanstack/vue-query'
import { computed, toValue, type MaybeRefOrGetter } from 'vue'
import apiClient from '@/api/client'

interface PromptDefaults {
  vision_prompt: string
  category_prompts: Record<string, string>
}

/** 只读获取默认提示词；重置仅填入表单，保存后才生效。 */
export function usePromptDefaults(enabled: MaybeRefOrGetter<boolean>) {
  return useQuery({
    queryKey: ['prompt-defaults'],
    queryFn: async () => (await apiClient.get<PromptDefaults>('/config/prompt-defaults')).data,
    enabled: computed(() => toValue(enabled)),
    staleTime: Infinity,
  })
}
