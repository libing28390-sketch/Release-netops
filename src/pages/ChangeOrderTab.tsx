import React from 'react';
import ChangeOrderComponent from './ChangeOrder';
import type { Props } from './ChangeOrder/types';

const ChangeOrderTab: React.FC<Props> = (props) => {
  return <ChangeOrderComponent {...props} />;
};

export default ChangeOrderTab;
