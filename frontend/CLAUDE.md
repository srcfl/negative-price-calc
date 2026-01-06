# [Project Name]

## UI Framework

This project uses the **Sourceful Design System**. All UI components must come from `@sourceful-energy/ui`.

```bash
npm install @sourceful-energy/ui
```

```tsx
// Required: Import styles in your root layout/app
import "@sourceful-energy/ui/styles.css"

// Import components as needed
import { Button, Card, Badge, Input, Label } from "@sourceful-energy/ui"
```

### Component Quick Reference

| Need | Use |
|------|-----|
| Actions | `Button` (variants: default, outline, destructive, energy, success, warning) |
| Status indicators | `Badge` (variants: default, secondary, destructive, outline, energy, success, warning, info) |
| Containers | `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter` |
| Forms | `Input`, `Label`, `Select`, `Checkbox`, `Switch`, `Textarea`, `Slider` |
| Feedback | `Alert`, `toast` (from sonner), `Progress`, `Skeleton` |
| Overlays | `Dialog`, `Sheet`, `DropdownMenu`, `Tooltip` |
| Layout | `Tabs`, `Accordion`, `Separator`, `ScrollArea`, `Table` |
| Brand | `Logo` (variants: full, symbol, wordmark) |

### Key Patterns

```tsx
// Theme: Uses next-themes with class strategy
// All components support dark mode automatically

// Colors: Use semantic tokens
className="text-primary"        // Sourceful green
className="text-destructive"    // Error red
className="bg-muted"            // Subtle background
className="text-muted-foreground" // Secondary text

// Toasts
import { toast } from "sonner"
toast.success("Saved")
toast.error("Failed")

// Forms: Always pair Label with inputs
<div className="space-y-2">
  <Label htmlFor="email">Email</Label>
  <Input id="email" type="email" />
</div>
```

### Don't

- Don't create custom buttons, cards, or form inputs - use the design system
- Don't use raw colors like `#22c55e` - use tokens like `text-primary`
- Don't install shadcn/ui directly - components are already included
- Don't create custom modal/dialog components - use `Dialog` or `Sheet`

## Project-Specific Notes

<!-- Add your project-specific context below -->

