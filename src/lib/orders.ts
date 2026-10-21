/** Human-friendly order reference derived from the id, e.g. "NF-8K2Q1ZJ4". */
export function orderNumber(orderId: string): string {
  return `NF-${orderId.slice(-8).toUpperCase()}`;
}
