declare module 'jszip' {
  export interface JSZipObject {
    dir: boolean;
    async(type: 'string'): Promise<string>;
  }

  export default class JSZip {
    files: Record<string, JSZipObject>;
    static loadAsync(data: Blob | ArrayBuffer): Promise<JSZip>;
  }
}

declare module 'react-markdown' {
  import type { ComponentType, ReactNode } from 'react';

  export interface ReactMarkdownProps {
    children?: string;
    remarkPlugins?: unknown[];
    components?: Record<string, ComponentType<any>>;
  }

  const ReactMarkdown: ComponentType<ReactMarkdownProps>;
  export default ReactMarkdown;
}

declare module 'remark-gfm' {
  const remarkGfm: unknown;
  export default remarkGfm;
}
