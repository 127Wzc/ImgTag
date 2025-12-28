import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * 合并 Tailwind CSS 类名
 * 使用 clsx 处理条件类名，tailwind-merge 合并冲突类
 */
export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs))
}
