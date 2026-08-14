import { cva, type VariantProps } from "class-variance-authority"
import { type ButtonHTMLAttributes, forwardRef } from "react"
import { cn } from "../../lib/utils"

const buttonVariants = cva("inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:pointer-events-none disabled:opacity-50", {
  variants: {
    variant: {
      default: "bg-[#151b23] text-white hover:bg-[#27313c]",
      secondary: "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
      ghost: "text-slate-500 hover:bg-slate-100 hover:text-slate-900",
      brand: "bg-brand-500 text-white hover:bg-brand-600",
    },
    size: { default: "h-10 px-4 py-2", sm: "h-8 px-3 text-xs", icon: "h-10 w-10" },
  },
  defaultVariants: { variant: "default", size: "default" },
})

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, ...props }, ref) => (
  <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
))
Button.displayName = "Button"
