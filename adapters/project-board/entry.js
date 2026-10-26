/** Small host for the pinned native Hermes board; real upstream UI primitives.
 * The upstream component/SDK contracts are MIT, Nous Research. See build notices.
 */
import React, { useState, useEffect, useCallback, useMemo, useRef, useContext, createContext } from 'react';
import { createRoot } from 'react-dom/client';
import { Badge } from '@nous-research/ui/ui/components/badge';
import { Button } from '@nous-research/ui/ui/components/button';
import { Checkbox } from '@nous-research/ui/ui/components/checkbox';
import { ConfirmDialog } from '@nous-research/ui/ui/components/confirm-dialog';
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@nous-research/ui/ui/components/dialog';
import { Toast } from '@nous-research/ui/ui/components/toast';
import { Select, SelectOption } from '@nous-research/ui/ui/components/select';
import { Card, CardHeader, CardTitle, CardContent } from '@nous-research/ui/ui/components/card';
import { Input } from '@nous-research/ui/ui/components/input';
import { Label } from '@nous-research/ui/ui/components/label';
import { Separator } from '@nous-research/ui/ui/components/separator';
import { Tabs, TabsList, TabsTrigger } from '@nous-research/ui/ui/components/tabs';
import { useConfirmDelete } from '@nous-research/ui/hooks/use-confirm-delete';
import { useToast } from '@nous-research/ui/hooks/use-toast';
import { cn, timeAgo, isoTimeAgo } from './native-utils.ts';
import './style.css';

const h = React.createElement;
const fetchJSON = async (url, options = {}) => {
  if ((options.method || 'GET').toUpperCase() !== 'GET') throw new Error('Read only: this action is unavailable');
  const target = new URL(url, location.href);
  if (target.origin !== location.origin) throw new Error('Only this local project view is available');
  const response = await fetch(target, { ...options, credentials: 'same-origin', cache: 'no-store' });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Project read failed');
  return value;
};
const ReadButton = React.forwardRef((props, ref) => {
  const name = String(props['aria-label'] || props.title || (typeof props.children === 'string' ? props.children : ''));
  const close = /^close(?:\b|\s|\()/i.test(name);
  return h(Button, { ...props, ref, disabled: props.disabled || !close,
    title: close ? props.title : 'Read only: this control is unavailable' });
});
ReadButton.displayName = 'ReadOnlyNativeButton';
const ReadInput = React.forwardRef((props, ref) => h(Input, { ...props, ref,
  readOnly: props.readOnly || !/^(search|filter cards)/i.test(String(props.placeholder || '')) }));
ReadInput.displayName = 'ReadOnlyNativeInput';
window.__HERMES_PLUGIN_SDK__ = {
  sdkVersion: '1.1.0', readOnly: true, React,
  hooks: { useState, useEffect, useCallback, useMemo, useRef, useContext, createContext, useConfirmDelete, useToast },
  fetchJSON, authedFetch: async (url, options) => {
    if (options && options.method && options.method.toUpperCase() !== 'GET') throw new Error('Read only');
    return fetch(url, { ...options, credentials: 'same-origin' });
  },
  components: { Card, CardHeader, CardTitle, CardContent, Badge, Button: ReadButton,
    Checkbox: props => h(Checkbox, { ...props, disabled: true }), ConfirmDialog, Dialog, DialogClose,
    DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Toast,
    Input: ReadInput, Label, Select: props => h(Select, { ...props, disabled: true }),
    SelectOption, Separator, Tabs, TabsList, TabsTrigger },
  utils: { cn, timeAgo, isoTimeAgo },
};
window.__HERMES_PLUGINS__ = { register(name, component) {
  if (name !== 'kanban') throw new Error('Unexpected native plugin');
  createRoot(document.getElementById('board')).render(h(component));
} };
document.addEventListener('dragstart', event => event.preventDefault(), true);
document.addEventListener('drop', event => event.preventDefault(), true);
document.addEventListener('pointerdown', event => {
  if (event.target.closest('[draggable="true"]')) event.stopPropagation();
}, true);
let mobileColumnShown = false;
const disableRawEditors = () => {
  document.querySelectorAll('#board button').forEach(node => {
    if (!/^close(?:\b|\s|\()/i.test(node.getAttribute('aria-label') || node.title || node.textContent || '')) node.disabled = true;
  });
  document.querySelectorAll('textarea').forEach(node => { node.readOnly = true; });
  document.querySelectorAll('[draggable="true"]').forEach(node => { node.draggable = false; });
  document.querySelectorAll('a[href*="/attachments/"]').forEach(node => {
    node.setAttribute('aria-disabled', 'true'); node.title = 'Attachment delivery is not available in this read view';
  });
  const columns = document.querySelector('.hermes-kanban-columns');
  const firstCard = document.querySelector('.hermes-kanban-card');
  if (!mobileColumnShown && innerWidth < 600 && columns && firstCard) {
    columns.scrollLeft = firstCard.closest('.hermes-kanban-column').offsetLeft - columns.offsetLeft;
    mobileColumnShown = true;
  }
};
document.addEventListener('click', event => {
  if (event.target.closest('a[aria-disabled="true"]')) event.preventDefault();
}, true);
new MutationObserver(disableRawEditors).observe(document.getElementById('board'), { childList: true, subtree: true });
window.addEventListener('resize', disableRawEditors);
document.getElementById('reload').addEventListener('click', () => location.reload());
fetchJSON('/api/project-board').then(project => {
  document.getElementById('project-name').textContent = project.name;
  document.getElementById('project-name').title = project.project_root;
  document.getElementById('project-id').textContent = project.project_id;
  const native = document.createElement('script'); native.src = '/native-board.js';
  native.onerror = () => { document.getElementById('board').textContent = 'Native board assets could not load.'; };
  document.body.append(native);
}).catch(error => { document.getElementById('board').textContent = error.message; });
