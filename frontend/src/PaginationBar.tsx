type PaginationBarProps = {
  total: number;
  itemLabel: string;
  pageSize?: number;
  page: number;
  totalPages: number;
  onPrevious: () => void;
  onNext: () => void;
  previousDisabled: boolean;
  nextDisabled: boolean;
};

export function PaginationBar({ total, itemLabel, pageSize, page, totalPages, onPrevious, onNext, previousDisabled, nextDisabled }: PaginationBarProps) {
  return <div className="pagination-bar"><span>共 {total} {itemLabel}</span>{pageSize && <span className="pagination-page-size">每页 {pageSize} 条</span>}<button type="button" disabled={previousDisabled} onClick={onPrevious}>上一页</button><span className="page-number" aria-current="page">{page}</span><button type="button" disabled={nextDisabled} onClick={onNext}>下一页</button><span>第 {page} / {totalPages} 页</span></div>;
}
