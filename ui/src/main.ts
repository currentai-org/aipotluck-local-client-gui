import { mount } from 'svelte';
import './design/fonts.css';
import './design/tokens.css';
import './design/base.css';
import './app.css';
import App from './App.svelte';

export default mount(App, { target: document.getElementById('app')! });
