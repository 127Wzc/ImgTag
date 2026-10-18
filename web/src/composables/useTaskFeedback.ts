import { useQueryClient } from '@tanstack/vue-query'
import { useRouter } from 'vue-router'
import { notifySuccess } from '@/utils/notify'

/** 入队后统一反馈；单个任务可直接查看详情，批量任务进入队列。 */
export function useTaskFeedback() {
  const router = useRouter()
  const queryClient = useQueryClient()

  return (message: string, taskId?: string) => {
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    notifySuccess(message, {
      duration: 7000,
      action: {
        label: '查看任务',
        onClick: () => { void router.push({ path: '/tasks', query: taskId ? { task: taskId } : {} }) },
      },
    })
  }
}
