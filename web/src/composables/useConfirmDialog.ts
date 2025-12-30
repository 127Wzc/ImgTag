/**
 * 确认弹窗 composable
 * 提供全局可复用的确认弹窗功能
 * 
 * 使用方式：
 * const { confirm, ConfirmDialogState, handleConfirm, handleCancel } = useConfirmDialog()
 * 
 * async function deleteItem() {
 *   const confirmed = await confirm({
 *     title: '删除确认',
 *     message: '确定要删除吗？',
 *     variant: 'danger'
 *   })
 *   if (confirmed) {
 *     // 执行删除
 *   }
 * }
 */
import { reactive } from 'vue'

interface ConfirmOptions {
    title?: string
    message: string
    confirmText?: string
    cancelText?: string
    variant?: 'default' | 'warning' | 'danger'
    // 可选的复选框
    checkboxLabel?: string
    checkboxDefault?: boolean
}

interface ConfirmState {
    open: boolean
    title: string
    message: string
    confirmText: string
    cancelText: string
    variant: 'default' | 'warning' | 'danger'
    loading: boolean
    // 复选框状态
    checkboxLabel: string
    checkboxChecked: boolean
}

// 确认结果（包含复选框状态）
interface ConfirmResult {
    confirmed: boolean
    checkboxChecked: boolean
}

export function useConfirmDialog() {
    const state = reactive<ConfirmState>({
        open: false,
        title: '确认操作',
        message: '',
        confirmText: '确定',
        cancelText: '取消',
        variant: 'default',
        loading: false,
        checkboxLabel: '',
        checkboxChecked: false,
    })

    let resolvePromise: ((value: ConfirmResult) => void) | null = null

    /**
     * 显示确认弹窗
     * @returns Promise that resolves to ConfirmResult with confirmed and checkboxChecked
     */
    function confirm(options: ConfirmOptions): Promise<ConfirmResult> {
        return new Promise((resolve) => {
            state.title = options.title || '确认操作'
            state.message = options.message
            state.confirmText = options.confirmText || '确定'
            state.cancelText = options.cancelText || '取消'
            state.variant = options.variant || 'default'
            state.loading = false
            state.checkboxLabel = options.checkboxLabel || ''
            state.checkboxChecked = options.checkboxDefault ?? false
            state.open = true
            resolvePromise = resolve
        })
    }

    function handleConfirm() {
        if (resolvePromise) {
            resolvePromise({ confirmed: true, checkboxChecked: state.checkboxChecked })
            resolvePromise = null
        }
        state.open = false
    }

    function handleCancel() {
        if (resolvePromise) {
            resolvePromise({ confirmed: false, checkboxChecked: false })
            resolvePromise = null
        }
        state.open = false
    }

    function setLoading(loading: boolean) {
        state.loading = loading
    }

    return {
        state,
        confirm,
        handleConfirm,
        handleCancel,
        setLoading,
    }
}
