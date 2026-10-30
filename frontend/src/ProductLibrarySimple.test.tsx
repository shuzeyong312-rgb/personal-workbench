import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import { ProductLibrarySimple } from './ProductLibrarySimple';

test('shows the single-sheet import and product list without the retired five-sheet workflow', () => {
  const html = renderToStaticMarkup(<ProductLibrarySimple />);
  expect(html).toContain('下载八列模板');
  expect(html).toContain('旧六列价格须另行核对');
  expect(html).toContain('产品列表');
  expect(html).not.toContain('参数明细');
  expect(html).not.toContain('价格类型');
});
