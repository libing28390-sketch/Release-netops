import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import { U_PX } from '../constants';

interface DroppableSlotProps {
  uNumber: number;
  isGhostHere: boolean;
  ghostConflict: boolean;
  ghostHeight: number;
  ghostIsStart: boolean;
}

export const DroppableSlot: React.FC<DroppableSlotProps> = ({
  uNumber,
  isGhostHere,
  ghostConflict,
  ghostHeight,
  ghostIsStart,
}) => {
  const { setNodeRef } = useDroppable({ id: `slot-${uNumber}` });

  return (
    <div
      ref={setNodeRef}
      className="absolute"
      style={{ left: 0, right: 0, top: 0, height: U_PX }}
    >
      {isGhostHere && ghostIsStart && (
        <div
          className="absolute inset-x-0 rounded-[3px] pointer-events-none transition-all duration-100"
          style={{
            top: 0,
            height: ghostHeight * U_PX - 2,
            background: ghostConflict ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.15)',
            border: ghostConflict ? '2px dashed #ef4444' : '2px dashed #10b981',
            zIndex: 5,
          }}
        />
      )}
    </div>
  );
};

export default DroppableSlot;
