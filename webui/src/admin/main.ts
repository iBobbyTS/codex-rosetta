import { mount } from 'svelte';
import App from './App.svelte';
import '@ibobbyts/svelte-ui-utils/style.css';
import './styles.css';

mount(App, { target: document.getElementById('app')! });
